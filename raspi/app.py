"""
app.py  –  Task 5: Flask web UI for MarauderMini edge server.

Routes:
  GET  /                  Dashboard (live readings + stats)
  GET  /api/latest        JSON  – latest telemetry row
  GET  /api/history       JSON  – last N readings for chart
  GET  /api/stats         JSON  – min/max/avg over last 24 h
  GET  /api/alerts        JSON  – recent alerts
  GET  /api/menu          JSON  – live ESP32 menu/joystick state
  GET  /rules             Rules management page
  POST /rules/create      Create a new rule
  POST /rules/<id>/update Update a rule
  POST /rules/<id>/toggle Enable / disable a rule
  POST /rules/<id>/delete Delete a rule
  POST /control/<cmd>     Queue a scan/start/stop/reset command for the ESP32
                          (picked up and sent over Serial by serial_bridge.py)

Run:
    python app.py
"""

import json
import os
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for, flash
from dotenv import load_dotenv

from db import get_conn
import analytics

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev_secret_change_me")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_json(row: dict) -> dict:
    """Convert MariaDB row to JSON-serialisable dict (handle datetime, Decimal)."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = float(v) if hasattr(v, "__float__") and not isinstance(v, (int, bool)) else v
    return out


def get_latest() -> dict | None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM telemetry ORDER BY recorded_at DESC LIMIT 1"
            )
            return cur.fetchone()
    finally:
        conn.close()


def get_history(limit: int = 60) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recorded_at, deauth_active, deauth_pkts, tx_errors,
                       clients_found, send_interval_ms, device_uptime_s
                FROM telemetry
                ORDER BY recorded_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            return list(reversed(rows))   # chronological order for charts
    finally:
        conn.close()


# Commands the ESP32's handleSerial() actually understands
# (see marauder_mini/marauder_mini.ino) — keep in sync with that switch.
VALID_COMMANDS = {"scan", "start", "stop", "reset"}


def queue_command(command: str) -> None:
    """Queue a command for serial_bridge.py to forward to the ESP32.

    app.py doesn't hold the serial connection itself (serial_bridge.py does,
    in a separate process), so commands are handed off via the DB instead.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO commands (command) VALUES (%s)", (command,))
    finally:
        conn.close()


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    latest = get_latest()
    stats  = analytics.get_stats(hours=24)
    alerts = analytics.get_recent_alerts(limit=5)
    return render_template(
        "dashboard.html",
        latest=latest,
        stats=stats,
        alerts=alerts,
        now=datetime.utcnow(),
    )


@app.route("/rules")
def rules_page():
    all_rules = analytics.get_all_rules()
    return render_template("rules.html", rules=all_rules)


# ── Rule CRUD ─────────────────────────────────────────────────────────────────

@app.route("/rules/create", methods=["POST"])
def rule_create():
    try:
        analytics.create_rule(
            name        = request.form["name"].strip(),
            metric      = request.form["metric"],
            operator    = request.form["operator"],
            threshold   = float(request.form["threshold"]),
            action      = request.form["action"],
            action_param= request.form.get("action_param", "").strip(),
        )
        flash("Rule created.", "success")
    except Exception as exc:
        flash(f"Error: {exc}", "danger")
    return redirect(url_for("rules_page"))


@app.route("/rules/<int:rule_id>/update", methods=["POST"])
def rule_update(rule_id: int):
    try:
        analytics.update_rule(
            rule_id,
            name        = request.form["name"].strip(),
            metric      = request.form["metric"],
            operator    = request.form["operator"],
            threshold   = float(request.form["threshold"]),
            action      = request.form["action"],
            action_param= request.form.get("action_param", "").strip(),
        )
        flash("Rule updated.", "success")
    except Exception as exc:
        flash(f"Error: {exc}", "danger")
    return redirect(url_for("rules_page"))


@app.route("/rules/<int:rule_id>/toggle", methods=["POST"])
def rule_toggle(rule_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT enabled FROM rules WHERE id=%s", (rule_id,))
            row = cur.fetchone()
            if row:
                new_state = 0 if row["enabled"] else 1
                analytics.update_rule(rule_id, enabled=new_state)
                flash(f"Rule {'enabled' if new_state else 'disabled'}.", "success")
    finally:
        conn.close()
    return redirect(url_for("rules_page"))


@app.route("/rules/<int:rule_id>/delete", methods=["POST"])
def rule_delete(rule_id: int):
    try:
        analytics.delete_rule(rule_id)
        flash("Rule deleted.", "success")
    except Exception as exc:
        flash(f"Error: {exc}", "danger")
    return redirect(url_for("rules_page"))


# ── ESP32 remote control ──────────────────────────────────────────────────────

@app.route("/control/<cmd>", methods=["POST"])
def control(cmd: str):
    if cmd not in VALID_COMMANDS:
        flash(f"Unknown command '{cmd}'.", "danger")
        return redirect(url_for("dashboard"))
    try:
        queue_command(cmd)
        flash(f"Command '{cmd}' queued — sent to ESP32 within a couple seconds.", "success")
    except Exception as exc:
        flash(f"Error queuing command: {exc}", "danger")
    return redirect(url_for("dashboard"))


# ── JSON API (used by dashboard JS for live updates) ─────────────────────────

@app.route("/api/latest")
def api_latest():
    row = get_latest()
    if row is None:
        return jsonify({"error": "no data"}), 404
    return jsonify(_row_to_json(row))


@app.route("/api/history")
def api_history():
    limit = min(int(request.args.get("limit", 60)), 300)
    rows  = get_history(limit)
    return jsonify([_row_to_json(r) for r in rows])


@app.route("/api/stats")
def api_stats():
    hours = int(request.args.get("hours", 24))
    stats = analytics.get_stats(hours)
    return jsonify(_row_to_json(stats) if stats else {})


@app.route("/api/menu")
def api_menu():
    """Latest ESP32 menu/joystick state, cached by serial_bridge.py from
    the "type":"menu" packets emitted by showMenu() in the firmware."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT payload_json, updated_at FROM menu_state WHERE id = 1")
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return jsonify({})

    payload = json.loads(row["payload_json"])
    payload["updated_at"] = row["updated_at"].isoformat()
    return jsonify(payload)


@app.route("/api/alerts")
def api_alerts():
    limit  = min(int(request.args.get("limit", 20)), 100)
    alerts = analytics.get_recent_alerts(limit)
    return jsonify([_row_to_json(a) for a in alerts])


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
