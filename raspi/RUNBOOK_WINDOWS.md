# MarauderMini Runbook - Emergency (Edge Layer on a Windows laptop)

> Use this when the Raspberry Pi isn't working. The whole stack (MariaDB +
> serial bridge + web UI) runs directly on this Windows laptop, with the
> ESP32 plugged straight into its USB port. No SSH/SCP needed since
> everything runs locally.

---

## Part 1: Install MariaDB on Windows
One-time.

- [ ] Download MariaDB Community Server (Windows MSI build) at: https://mariadb.org/download/
- [ ] Run the `.msi` file, click Next through the steps
- [ ] At the "Modify Password" step: set a root password and remember it
  (unlike Linux, MariaDB on Windows requires a password to be set)
- [ ] Keep the default port 3306, Next, Install
- [ ] After installation, confirm the service is running:
  - Open Services (type `services.msc` in the Start Menu)
  - Find the `MariaDB` entry, Status should be Running

---

## Part 2: Prepare Python
One-time.

Open PowerShell and go to the project folder:
```
cd "C:\Users\tuanp\Documents\Learning\IOT Programming\Individual\raspi"
```

Create the virtual environment and install dependencies:
```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- [ ] If PowerShell reports "cannot be loaded because running scripts is
  disabled" when activating the venv, run this and try again:
  ```
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

---

## Part 3: Create the `.env` file

Create `raspi/.env` (using Notepad or VS Code) with this content:

```
# MariaDB connection
DB_HOST=localhost
DB_PORT=3306
DB_NAME=marauder_db
DB_USER=root
DB_PASS=<the password you set in Part 1>

# ESP32 serial port - updated later in Part 5
SERIAL_PORT=COM3
SERIAL_BAUD=115200

# Flask
FLASK_SECRET=change_me_please
FLASK_PORT=5000
```

- [ ] `.env` saved in the `raspi/` folder

---

## Part 4: Initialize the database

Still in PowerShell (venv activated from Part 2):
```
python init_db.py
```

Expected output:
```
Connecting to localhost:3306 as root ...
OK: CREATE DATABASE IF NOT EXISTS marauder_db...
OK: CREATE TABLE IF NOT EXISTS telemetry...
OK: CREATE TABLE IF NOT EXISTS rules...
OK: CREATE TABLE IF NOT EXISTS alerts...
OK: INSERT INTO rules...

Database initialised successfully.
Tables created: telemetry, rules, alerts (3 default rules seeded).
```

- [ ] "Database initialised successfully." shown -> DB OK
- [ ] If you get `Access denied for user 'root'`, check `DB_PASS` in `.env`

Note: this script is not idempotent for the seed rules - running `init_db.py`
more than once will insert the 3 default rules again as duplicates (the
database/tables themselves are safe thanks to `IF NOT EXISTS`). Run it once;
if you did run it more than once, delete the duplicate rules from the
`/rules` page in the web UI.

---

## Part 5: Plug in the ESP32 and find its COM port

- [ ] Unplug the ESP32 from the Arduino IDE / any other machine
- [ ] Plug the ESP32 directly into this laptop's USB port
- [ ] Open Device Manager (`devmgmt.msc`), section "Ports (COM & LPT)"
- [ ] Look for an entry like "Silicon Labs CP210x USB to UART Bridge (COMx)"
  or "USB-SERIAL CH340 (COMx)" and note the COM number

Update `.env`:
```
SERIAL_PORT=COM3    # change to the COM number you just found
```

Note: close the Arduino IDE's Serial Monitor before running
`serial_bridge.py` - Windows only lets one program hold a COM port at a
time. If both are open, `serial_bridge.py` will fail with a
`PermissionError` / "Access is denied".

---

## Part 6: Run the system
Every time you want to use it - needs 2 PowerShell windows.

### Window 1: Serial Bridge
```
cd "C:\Users\tuanp\Documents\Learning\IOT Programming\Individual\raspi"
.\venv\Scripts\Activate.ps1
python serial_bridge.py
```
Expected output:
```
INFO     Serial bridge starting on COM3 @ 115200 baud
INFO     Connected to ESP32 on COM3
INFO     Database connection established
INFO     Stored row #1  deauth=OFF  pkts=0  uptime=6s
```

### Window 2: Web UI
```
cd "C:\Users\tuanp\Documents\Learning\IOT Programming\Individual\raspi"
.\venv\Scripts\Activate.ps1
python app.py
```
Expected output:
```
 * Running on http://0.0.0.0:5000
```

- [ ] Open a browser at `http://localhost:5000`
- [ ] Dashboard shows Deauth status and packet count -> system working

---

## Part 7: Shutting down

In each PowerShell window, press Ctrl+C to stop the process.

---

## Part 8: Troubleshooting (Windows)

| Symptom | Cause | Fix |
|---|---|---|
| `PermissionError` / "Access is denied" opening the COM port | Arduino IDE's Serial Monitor (or another program) is holding the port | Close Serial Monitor and any other window using that COM port |
| `could not open port 'COM3'` | Wrong COM number, or ESP32 not plugged in | Check Device Manager, try reseating the USB cable |
| `Access denied for user 'root'@'localhost'` | Wrong `DB_PASS` in `.env` | Check the password you set when installing MariaDB |
| `Can't connect to MySQL server on 'localhost'` | MariaDB service not running | Open `services.msc`, start the `MariaDB` service |
| `cannot be loaded because running scripts is disabled` | PowerShell execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `Address already in use: 5000` | Port taken by something else | Change `FLASK_PORT=5001` in `.env` |
| `ModuleNotFoundError` | Forgot to activate the venv | Run `.\venv\Scripts\Activate.ps1` first |
| Dashboard blank / no data | Serial Bridge not running, or no `JSON:` received from the ESP32 yet | Check Window 1 for a "Stored row #..." line |

---

## When the Raspberry Pi is working again

No code changes needed - `raspi/` has nothing Windows-specific in it (the
only difference is in `.env`: `SERIAL_PORT` and possibly `DB_HOST`). To
switch back to the Pi, just follow `RUNBOOK.md` as usual.
