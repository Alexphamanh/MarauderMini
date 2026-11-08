#!/usr/bin/env bash
# ============================================================
#  setup.sh  –  Bootstrap MarauderMini edge stack on RPi
#  Usage:  bash setup.sh
# ============================================================
set -e

echo "==> [1/4] Install system packages"
sudo apt-get update -qq
sudo apt-get install -y mariadb-server python3 python3-pip python3-venv

echo "==> [2/4] Create Python virtual environment"
python3 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "==> [3/4] Initialise MariaDB database"
# Prompt for root password; creates DB + tables from schema.sql
echo "Enter MariaDB root password (press Enter if none):"
read -rs DB_PASS

if [ -z "$DB_PASS" ]; then
    sudo mariadb < schema.sql
else
    sudo mariadb -p"$DB_PASS" < schema.sql
fi

echo "==> [4/4] Create .env config file"
cat > .env <<EOF
# MariaDB connection
DB_HOST=localhost
DB_PORT=3306
DB_NAME=marauder_db
DB_USER=root
DB_PASS=${DB_PASS}

# Serial port of ESP32 (change to /dev/ttyUSB0 if needed)
SERIAL_PORT=/dev/ttyUSB0
SERIAL_BAUD=115200

# Flask
FLASK_SECRET=change_me_please
FLASK_PORT=5000
EOF

echo ""
echo "Done! Edit .env if needed, then:"
echo "  source venv/bin/activate"
echo "  python serial_bridge.py &   # reads ESP32, inserts to DB"
echo "  python app.py               # starts web UI on :5000"
