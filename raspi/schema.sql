-- ============================================================
--  MarauderMini – MariaDB Schema
--  Run as root: mysql -u root -p < schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS marauder_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE marauder_db;

-- ── Telemetry (from ESP32 via Serial) ─────────────────────
-- Matches the JSON:{...} payload actually emitted by marauder_mini.ino:
-- {"type":"telemetry","deauth_active":bool,"deauth_pkts":int,"tx_errors":int,
--  "clients_found":int,"send_interval_ms":int,"ts":uptime_seconds}
CREATE TABLE IF NOT EXISTS telemetry (
  id                BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  recorded_at       DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deauth_active     TINYINT(1)       NOT NULL DEFAULT 0,
  deauth_pkts       BIGINT UNSIGNED  NOT NULL DEFAULT 0,
  tx_errors         BIGINT UNSIGNED  NOT NULL DEFAULT 0,
  clients_found     INT UNSIGNED     NOT NULL DEFAULT 0,
  send_interval_ms  INT UNSIGNED     NOT NULL DEFAULT 0,
  device_uptime_s   BIGINT UNSIGNED  NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  INDEX idx_recorded_at (recorded_at)
) ENGINE=InnoDB;

-- ── Edge analytics rule definitions ───────────────────────
CREATE TABLE IF NOT EXISTS rules (
  id           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  name         VARCHAR(80)   NOT NULL,
  metric       VARCHAR(40)   NOT NULL COMMENT 'deauth_active, deauth_pkts, or device_uptime_s',
  operator     ENUM('>','<','>=','<=','==','!=') NOT NULL,
  threshold    DECIMAL(10,4) NOT NULL,
  action       VARCHAR(40)   NOT NULL COMMENT 'log_alert, or stop_attack/start_attack/reset_device (sent back over Serial)',
  action_param VARCHAR(255)  DEFAULT NULL COMMENT 'log_alert message, or Serial command override',
  enabled      TINYINT(1)    NOT NULL DEFAULT 1,
  created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB;

-- ── Alert log (every time a rule fires) ───────────────────
CREATE TABLE IF NOT EXISTS alerts (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  rule_id      INT UNSIGNED    NOT NULL,
  telemetry_id BIGINT UNSIGNED NOT NULL,
  fired_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  metric_value DECIMAL(10,4)   NOT NULL,
  message      VARCHAR(255)    NOT NULL,
  PRIMARY KEY (id),
  INDEX idx_fired_at  (fired_at),
  FOREIGN KEY (rule_id)      REFERENCES rules(id)     ON DELETE CASCADE,
  FOREIGN KEY (telemetry_id) REFERENCES telemetry(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ── Live menu/joystick state (ESP32 → serial_bridge.py → web) ─────
-- Single-row cache of the last "type":"menu" JSON packet emitted by
-- showMenu() in marauder_mini.ino, so the web dashboard can mirror
-- exactly what's on the Serial menu (current screen, highlighted
-- item/AP) while the physical joystick is being used.
CREATE TABLE IF NOT EXISTS menu_state (
  id           TINYINT UNSIGNED NOT NULL PRIMARY KEY DEFAULT 1,
  payload_json TEXT             NOT NULL,
  updated_at   DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ── Command queue (web UI → serial_bridge.py → ESP32) ─────
-- app.py (Flask, its own process) cannot write to the serial port that
-- serial_bridge.py owns, so commands from the web UI are queued here;
-- serial_bridge.py polls this table and forwards them over Serial.
CREATE TABLE IF NOT EXISTS commands (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  command    VARCHAR(40)     NOT NULL COMMENT 'scan, start, stop, or reset',
  created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  sent_at    DATETIME        DEFAULT NULL,
  PRIMARY KEY (id),
  INDEX idx_sent_at (sent_at)
) ENGINE=InnoDB;

-- ── Seed default rules ─────────────────────────────────────
-- NOTE on thresholds: sendDeauth() can push several thousand packets per
-- second, so deauth_pkts crosses even large numbers within a few seconds
-- of starting an attack. The safety cutoff below is disabled by default
-- for that reason — enable it from the Rules page only if you actually
-- want attacks to auto-stop after N packets, and raise/lower the
-- threshold to match how long you want a run to last.
INSERT INTO rules (name, metric, operator, threshold, action, action_param, enabled) VALUES
  ('Deauth Active Notification', 'deauth_active', '==', 1.00,      'log_alert',   'Deauth attack is currently running', 1),
  ('High Packet Count Warning',  'deauth_pkts',   '>=', 50000.00,  'log_alert',   'Deauth packet count is high',        1),
  ('Auto-Stop Safety Cutoff',    'deauth_pkts',   '>=', 500000.00, 'stop_attack', '',                                    0);
