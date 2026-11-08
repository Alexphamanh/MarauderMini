# MarauderMini Runbook (A to Z)

> Read top to bottom in order. Check each box as you complete it.

---

## Part 1: Hardware setup
One-time.

### 1.1 Install Arduino IDE on Windows
- [ ] Download Arduino IDE at https://www.arduino.cc/en/software
- [ ] Install and open it

### 1.2 Add the ESP32 board to Arduino IDE
- [ ] Open File > Preferences
- [ ] Paste into "Additional boards manager URLs":
  ```
  https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
  ```
- [ ] Open Tools > Board > Boards Manager, search `esp32`, install "esp32 by Espressif Systems"

### 1.3 Flash firmware to the ESP32
- [ ] Plug the ESP32 into the computer via USB
- [ ] Open `marauder_mini/marauder_mini.ino` in Arduino IDE
- [ ] Tools > Board: select `ESP32 Dev Module` (or your exact board)
- [ ] Tools > Port: select the COM port the ESP32 is on (e.g. `COM3`)
- [ ] Click Upload, wait for "Done uploading"
- [ ] Open Tools > Serial Monitor, baud `115200`
- [ ] You should see the menu plus a `JSON:{...}` line after ~5s -> firmware OK

### 1.4 Connect the hardware
- [ ] Unplug the ESP32 from the computer
- [ ] Plug the ESP32 into the Raspberry Pi via USB
- [ ] Power on the Raspberry Pi

---

## Part 2: Copy files to the Raspberry Pi
One-time.

### 2.1 Find the Pi's IP address
On the Pi (if you have a screen attached) or from the router:
```
hostname -I
```
Note the IP, e.g. `192.168.1.42`

### 2.2 Copy the `raspi/` folder from Windows to the Pi
On the Windows machine, open Command Prompt:
```
scp -r "C:\Users\tuanp\Documents\Learning\IOT Programming\Individual\raspi" pi@192.168.1.42:~/
```
- [ ] Enter the Pi's password when prompted (default: `raspberry`)
- [ ] Wait for the copy to finish with no errors

Note: if SCP doesn't work, copy the `raspi/` folder to a USB drive, plug it into the Pi, and copy manually.

---

## Part 3: Bootstrap the Pi
One-time.

### 3.1 SSH into the Raspberry Pi
From Windows, open Command Prompt:
```
ssh pi@192.168.1.42
```
- [ ] Enter the password (default: `raspberry`)
- [ ] You should see the `pi@raspberrypi:~$` prompt -> SSH OK

### 3.2 Enter the folder and run setup
```
cd ~/raspi
chmod +x setup.sh
bash setup.sh
```

The script will automatically:
1. Install `mariadb-server`, `python3`, `python3-venv`
2. Create the Python virtual environment `venv/`
3. Install all packages from `requirements.txt`
4. Create the `marauder_db` database and all tables
5. Seed 3 default rules into the DB
6. Create the `.env` file

- [ ] The script asks "Enter MariaDB root password" -> press Enter (a fresh Pi has no password set)
- [ ] You should see `Done!` at the end -> setup OK

### 3.3 Check the database was created
```
sudo mariadb -e "USE marauder_db; SHOW TABLES;"
```
- [ ] You should see 3 tables: `alerts`, `rules`, `telemetry` -> DB OK

### 3.4 Check the .env file
```
cat ~/raspi/.env
```
- [ ] It should contain `DB_HOST`, `SERIAL_PORT`, `FLASK_PORT` -> OK

---

## Part 4: Check the serial port
Once, or whenever you replug the ESP32.

### 4.1 Find the ESP32's port
```
ls /dev/ttyUSB*
# or if that shows nothing:
ls /dev/ttyACM*
```
- [ ] You should see `/dev/ttyUSB0` or `/dev/ttyACM0`

### 4.2 Update .env if needed
```
nano ~/raspi/.env
```
- [ ] Edit the `SERIAL_PORT=/dev/ttyUSB0` line to match step 4.1's result
- [ ] Ctrl+O then Enter to save, Ctrl+X to exit

### 4.3 Grant serial read permission (if not already done)
```
sudo usermod -aG dialout $USER
```
- [ ] Log out and SSH back in for the permission to take effect:
  ```
  exit
  ssh pi@192.168.1.42
  ```

---

## Part 5: Run the system
Every time you want to use it.

Needs 2 SSH terminals into the Pi at once. Open 2 Command Prompt windows on Windows.

### Terminal 1: Serial Bridge

```
ssh pi@192.168.1.42
cd ~/raspi
source venv/bin/activate
python serial_bridge.py
```

Expected output:
```
2024-xx-xx  INFO     Serial bridge starting on /dev/ttyUSB0 @ 115200 baud
2024-xx-xx  INFO     Connected to ESP32 on /dev/ttyUSB0
2024-xx-xx  INFO     Database connection established
2024-xx-xx  INFO     Stored row #1  deauth=OFF  pkts=0  uptime=6s
```

- [ ] You should see "Connected to ESP32" -> serial OK
- [ ] You should see "Stored row #1" after ~5 seconds -> data reaching the DB OK
- [ ] If you see `[ALERT]` -> the analytics engine is running OK

### Terminal 2: Web UI

```
ssh pi@192.168.1.42
cd ~/raspi
source venv/bin/activate
python app.py
```

Expected output:
```
 * Running on http://0.0.0.0:5000
```

- [ ] You should see the line above -> server is running

### 5.1 Open the dashboard in a browser
- [ ] Open Chrome/Firefox on your computer
- [ ] Go to `http://192.168.1.42:5000`
- [ ] You should see the dashboard with Deauth status and packet count -> system working

---

## Part 6: Using the web UI

| Feature | URL |
|---|---|
| Dashboard (live data + chart) | `http://<Pi-IP>:5000` |
| Rules management | `http://<Pi-IP>:5000/rules` |

### Dashboard
- Metric cards auto-refresh every 10 seconds
- Chart shows the last 60 readings
- Alerts table shows the 5 most recent alerts

### Rules (Task 4)
- "New Rule": create a new rule
- Pencil icon: edit a rule
- Pause/Play icon: enable/disable a rule
- Trash icon: delete a rule

Metrics available in a rule:

| Metric | Description |
|---|---|
| `deauth_active` | Deauth attack running (0/1) |
| `deauth_pkts` | Number of deauth packets sent |
| `device_uptime_s` | ESP32 uptime in seconds |

Actions available:

| Action | Description |
|---|---|
| `log_alert` | Write an entry to the `alerts` table |
| `stop_attack` | Send `stop` to the ESP32 (stops the attack) |
| `start_attack` | Send `start` to the ESP32 (attacks all scanned APs) |
| `reset_device` | Send `reset` to the ESP32 |

Example rules (already seeded in the DB):
- `deauth_active == 1` -> `log_alert` -> "Deauth attack is currently running"
- `deauth_pkts >= 5000` -> `log_alert` -> "Deauth packet count is high"
- `deauth_pkts >= 20000` -> `stop_attack` -> automatically sends `stop` to the ESP32 (safety net to avoid runs going on too long)

---

## Part 7: Shutting down

In each terminal, press Ctrl+C to stop the process.

```
# Terminal 1
Ctrl+C   # stop serial_bridge.py

# Terminal 2
Ctrl+C   # stop app.py
```

---

## Part 8: Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Permission denied: /dev/ttyUSB0` | User lacks serial permission | `sudo usermod -aG dialout $USER`, then log out/in |
| `No such file: /dev/ttyUSB0` | ESP32 not detected | Check the USB cable, try `ls /dev/ttyACM*` |
| `Can't connect to MySQL server` | MariaDB not running | `sudo systemctl start mariadb` |
| Bridge connects but no data | ESP32 not flashed with the right firmware | Open Serial Monitor in Arduino IDE, check for `JSON:` lines |
| Dashboard blank / no data | Bridge not running | Make sure Terminal 1 is running `serial_bridge.py` |
| `Address already in use: 5000` | Port taken | Change `FLASK_PORT=5001` in `.env` |
| `ModuleNotFoundError` | Forgot to activate venv | Run `source venv/bin/activate` first |
| Can't SSH into the Pi | Wrong IP or SSH not enabled | On the Pi: `sudo systemctl enable ssh && sudo systemctl start ssh` |
