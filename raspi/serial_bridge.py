"""
serial_bridge.py  –  Task 2: Serial communication layer (RPi ↔ ESP32).

Reads lines from the ESP32 over USB-Serial.
Lines prefixed with "JSON:" are parsed and stored in MariaDB.
The analytics engine is called on each insertion.
All other lines are forwarded to stdout as debug logs.

Run:
    python serial_bridge.py

The process runs indefinitely; use Ctrl-C or systemd to stop it.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime

import serial
from dotenv import load_dotenv

from db import get_conn
import analytics

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

SERIAL_PORT  = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
SERIAL_BAUD  = int(os.getenv("SERIAL_BAUD", 115200))
RECONNECT_S  = 5   # seconds to wait before reconnect attempt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bridge.log"),
    ],
)
log = logging.getLogger("bridge")

# ── DB helpers ────────────────────────────────────────────────────────────────

def insert_telemetry(conn, data: dict) -> int:
    """Insert one telemetry row; return new row id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telemetry
              (recorded_at, deauth_active, deauth_pkts, tx_errors,
               clients_found, send_interval_ms, device_uptime_s)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                datetime.utcnow(),
                1 if data.get("deauth_active") else 0,
                data.get("deauth_pkts", 0),
                data.get("tx_errors", 0),
                data.get("clients_found", 0),
                data.get("send_interval_ms", 0),
                data.get("ts", 0),
            ),
        )
        return cur.lastrowid


# ── Live menu state (ESP32 → web) ─────────────────────────────────────────────

def store_menu_state(conn, data: dict) -> None:
    """Cache the latest "type":"menu" packet so the web UI can mirror the
    Serial menu (current screen, highlighted item/AP) in near-real-time.
    """
    payload = json.dumps(data)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO menu_state (id, payload_json) VALUES (1, %s)
            ON DUPLICATE KEY UPDATE payload_json = VALUES(payload_json)
            """,
            (payload,),
        )


# ── Web UI command queue ──────────────────────────────────────────────────────

def send_pending_commands(conn, ser) -> None:
    """Forward any commands queued by the web UI (app.py) to the ESP32.

    app.py runs in a separate process and has no access to this serial
    connection, so it queues commands in the `commands` table instead;
    we poll for unsent rows here and write them out over Serial.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id, command FROM commands WHERE sent_at IS NULL ORDER BY id")
        pending = cur.fetchall()

    for row in pending:
        try:
            ser.write((row["command"] + "\n").encode())
            log.info("[WEB CMD] Sent: %s", row["command"])
        except Exception as exc:
            log.error("Failed to send queued command '%s': %s", row["command"], exc)
        with conn.cursor() as cur:
            cur.execute("UPDATE commands SET sent_at = %s WHERE id = %s",
                        (datetime.utcnow(), row["id"]))


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_line(raw: str) -> dict | None:
    """
    Return parsed dict if the line is a JSON telemetry packet, else None.
    Expected format: JSON:{...}
    """
    raw = raw.strip()
    if not raw.startswith("JSON:"):
        return None
    try:
        return json.loads(raw[5:])
    except json.JSONDecodeError as exc:
        log.warning("Bad JSON payload: %s  (%s)", raw, exc)
        return None


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    log.info("Serial bridge starting on %s @ %d baud", SERIAL_PORT, SERIAL_BAUD)

    while True:
        ser = None
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
            log.info("Connected to ESP32 on %s", SERIAL_PORT)

            conn = get_conn()
            log.info("Database connection established")

            while True:
                try:
                    send_pending_commands(conn, ser)
                except Exception as exc:
                    log.error("Command queue error: %s", exc)

                try:
                    raw = ser.readline().decode("utf-8", errors="replace")
                except serial.SerialException as exc:
                    log.error("Serial read error: %s", exc)
                    break

                if not raw:
                    continue

                data = parse_line(raw)

                if data is None:
                    # Forward ESP32 debug output to our log
                    log.debug("[ESP32] %s", raw.strip())
                    continue

                if data.get("type") == "menu":
                    try:
                        store_menu_state(conn, data)
                    except Exception as exc:
                        log.error("Failed to store menu state: %s", exc)
                    continue

                # ── Store in DB ──────────────────────────────────────────
                try:
                    row_id = insert_telemetry(conn, data)
                    data["id"] = row_id          # analytics needs the DB id
                    # Map JSON keys → DB column names expected by analytics
                    data["device_uptime_s"] = data.get("ts", 0)

                    log.info(
                        "Stored row #%d  deauth=%s  pkts=%d  tx_errors=%d  "
                        "clients=%d  interval=%dms  uptime=%ds",
                        row_id,
                        "ON" if data.get("deauth_active") else "OFF",
                        data.get("deauth_pkts", 0),
                        data.get("tx_errors", 0),
                        data.get("clients_found", 0),
                        data.get("send_interval_ms", 0),
                        data.get("ts", 0),
                    )
                except Exception as exc:
                    log.error("DB insert failed: %s", exc)
                    # Attempt reconnect
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = get_conn()
                    continue

                # ── Run analytics / rules ────────────────────────────────
                try:
                    alerts = analytics.evaluate(data, serial_port=ser)
                    for alert in alerts:
                        log.warning("[ALERT] %s", alert["message"])
                except Exception as exc:
                    log.error("Analytics error: %s", exc)

        except serial.SerialException as exc:
            log.error("Cannot open serial port %s: %s", SERIAL_PORT, exc)

        except KeyboardInterrupt:
            log.info("Shutting down bridge (KeyboardInterrupt)")
            break

        finally:
            if ser and ser.is_open:
                ser.close()
            try:
                conn.close()
            except Exception:
                pass

        log.info("Reconnecting in %ds...", RECONNECT_S)
        time.sleep(RECONNECT_S)


if __name__ == "__main__":
    run()
