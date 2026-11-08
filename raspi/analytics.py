"""
analytics.py  –  Edge analytics engine (Task 4).

Loads rules from MariaDB, evaluates them against a telemetry reading,
logs alerts, and optionally sends an action command back to the ESP32
over the shared serial port.

Usage (standalone test):
    python analytics.py
"""

import logging
import operator as op
from datetime import datetime

from db import get_conn

logger = logging.getLogger(__name__)

# Map operator strings to Python callables
_OPS = {
    ">":  op.gt,
    "<":  op.lt,
    ">=": op.ge,
    "<=": op.le,
    "==": op.eq,
    "!=": op.ne,
}

# Actions that send a command back to the ESP32 via serial.
# Mapped to the real commands marauder_mini.ino's handleSerial() understands
# (see marauder_mini/marauder_mini.ino) — there is no buzzer/fan actuator on
# this device, but stopping/starting/resetting the attack is a real, useful
# automated action (e.g. an auto-stop safety cutoff after too many packets).
ACTION_COMMANDS = {
    "stop_attack":  "stop",
    "start_attack": "start",
    "reset_device": "reset",
}
SERIAL_ACTIONS = set(ACTION_COMMANDS)


def load_rules(conn) -> list[dict]:
    """Fetch all enabled rules from the DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM rules WHERE enabled = 1 ORDER BY id")
        return cur.fetchall()


def evaluate(telemetry: dict, serial_port=None) -> list[dict]:
    """
    Evaluate a telemetry dict against all active rules.

    Args:
        telemetry:   dict matching the JSON schema from the ESP32
                     {deauth_active, deauth_pkts, device_uptime_s, id (DB row id)}
        serial_port: open serial.Serial instance (optional) for back-commands

    Returns:
        List of alert dicts that were inserted into the DB.
    """
    conn = get_conn()
    try:
        rules = load_rules(conn)
        fired = []

        for rule in rules:
            metric    = rule["metric"]
            threshold = float(rule["threshold"])
            compare   = _OPS.get(rule["operator"])

            if compare is None:
                logger.warning("Unknown operator '%s' in rule id=%s", rule["operator"], rule["id"])
                continue

            value = telemetry.get(metric)
            if value is None:
                continue

            value = float(value)

            if compare(value, threshold):
                alert = _fire_alert(conn, rule, telemetry, value)
                fired.append(alert)

                # Send back-command to ESP32 if action requires it
                if rule["action"] in SERIAL_ACTIONS and serial_port and serial_port.is_open:
                    cmd = rule.get("action_param") or ACTION_COMMANDS[rule["action"]]
                    try:
                        serial_port.write((cmd + "\n").encode())
                        logger.info("[SERIAL CMD] Sent: %s", cmd)
                    except Exception as exc:
                        logger.error("Failed to write serial command: %s", exc)

        return fired
    finally:
        conn.close()


def _fire_alert(conn, rule: dict, telemetry: dict, value: float) -> dict:
    """Insert an alert row and return it."""
    message = (
        f"Rule '{rule['name']}': {rule['metric']} "
        f"{rule['operator']} {rule['threshold']} "
        f"(actual={value:.2f})"
    )
    logger.warning("[ALERT] %s", message)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alerts (rule_id, telemetry_id, fired_at, metric_value, message)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                rule["id"],
                telemetry.get("id", 0),
                datetime.utcnow(),
                value,
                message,
            ),
        )
        alert_id = cur.lastrowid

    return {
        "id":      alert_id,
        "rule":    rule["name"],
        "metric":  rule["metric"],
        "value":   value,
        "message": message,
        "action":  rule["action"],
    }


# ── Rule management helpers (used by Flask UI) ────────────────────────────────

def get_all_rules() -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM rules ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()


def create_rule(name: str, metric: str, operator: str,
                threshold: float, action: str,
                action_param: str = "") -> int:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rules (name, metric, operator, threshold, action, action_param)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (name, metric, operator, threshold, action, action_param),
            )
            return cur.lastrowid
    finally:
        conn.close()


def update_rule(rule_id: int, **kwargs) -> None:
    allowed = {"name", "metric", "operator", "threshold",
                "action", "action_param", "enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=%s" for k in fields)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE rules SET {set_clause} WHERE id=%s",
                (*fields.values(), rule_id),
            )
    finally:
        conn.close()


def delete_rule(rule_id: int) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rules WHERE id=%s", (rule_id,))
    finally:
        conn.close()


# ── Stats helpers (used by Flask UI) ─────────────────────────────────────────

def get_stats(hours: int = 24) -> dict:
    """
    Return min/max/avg deauth packet counts and reading counts over the
    last `hours` hours.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  ROUND(MIN(deauth_pkts), 0) AS pkts_min,
                  ROUND(MAX(deauth_pkts), 0) AS pkts_max,
                  ROUND(AVG(deauth_pkts), 0) AS pkts_avg,
                  ROUND(MAX(tx_errors), 0)   AS tx_errors_max,
                  ROUND(MAX(clients_found), 0) AS clients_max,
                  COALESCE(SUM(deauth_active), 0) AS active_readings,
                  COUNT(*)                   AS total_readings
                FROM telemetry
                WHERE recorded_at >= NOW() - INTERVAL %s HOUR
                """,
                (hours,),
            )
            return cur.fetchone() or {}
    finally:
        conn.close()


def get_recent_alerts(limit: int = 20) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.*, r.name AS rule_name, r.action
                FROM alerts a
                JOIN rules r ON r.id = a.rule_id
                ORDER BY a.fired_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ── Quick self-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    fake = {
        "id":              0,
        "deauth_active":   1,       # should trigger 'Deauth Active Notification'
        "deauth_pkts":     25000,   # should trigger 'High Packet Count Warning'
                                    # and 'Auto-Stop Safety Cutoff'
        "device_uptime_s": 60,
    }

    print("Testing analytics engine with fake telemetry:", fake)
    fired = evaluate(fake)
    if fired:
        print(f"  {len(fired)} alert(s) fired:")
        for a in fired:
            print(f"    • {a['message']}")
    else:
        print("  No rules triggered.")

    print("\nStats (last 24h):", get_stats(24))
