#!/bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Silakan jalankan skrip ini sebagai root (sudo su).${NC}"
  exit 1
fi

echo -e "${CYAN}=================================================${NC}"
echo -e "${GREEN}      PROSES TRANSISI INSTALASI WEB MANAGER      ${NC}"
echo -e "${CYAN}=================================================${NC}"

# 1. Pastikan folder path ada
mkdir -p /opt/gost-proxy/templates

# 2. Ambil dependensi core OS
echo -e "${YELLOW}[1/4] Memasang Python Virtual Env & dependencies...${NC}"
apt update -y && apt install -y python3 python3-venv python3-pip curl wget gzip iproute2 iputils-ping

# 3. Setup Python environment
cd /opt/gost-proxy
if [ ! -d "gost_env" ]; then
    python3 -m venv gost_env
fi
/opt/gost-proxy/gost_env/bin/pip install --upgrade pip
/opt/gost-proxy/gost_env/bin/pip install fastapi uvicorn requests pyTelegramBotAPI

# 4. Ambil binary GOST Engine jika belum terpasang
if [ ! -f /opt/gost-proxy/gost ]; then
    echo -e "${YELLOW}[2/4] Mendeteksi Arsitektur CPU & Mengunduh GOST Engine...${NC}"
    ARCH=$(uname -m)
    if [[ "$ARCH" == "x86_64" ]]; then GOST_ARCH="amd64"
    elif [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then GOST_ARCH="armv8"
    else GOST_ARCH="amd64"; fi
    
    wget -qO- "https://github.com/ginuerzh/gost/releases/download/v2.11.5/gost-linux-${GOST_ARCH}-2.11.5.gz" | gzip -d > /opt/gost-proxy/gost
    chmod +x /opt/gost-proxy/gost
fi

# 5. Nonaktifkan layanan CLI/TUI lama
echo -e "${YELLOW}[3/4] Menonaktifkan layanan TUI/CLI lama (jika ada)...${NC}"
systemctl disable gost-tui.service --now 2>/dev/null
pkill -9 -f "gost_tui"
pkill -9 -f "gost"

# 6. Buat file default config jika belum ada
if [ ! -f /opt/gost-proxy/settings.conf ]; then
    cat << 'EOF' > /opt/gost-proxy/settings.conf
ZONES=1081-1090
LANG_UI=ID
UI_INTERVAL=2
AUTO_REPORT_MINS=60
BOT_TOKEN=
CHAT_ID=
BOT_ENABLE=0
AUTO_FAILOVER=0
FINDIP_TOKEN=
FINDIP_ENABLE=0
PING_TARGET=8.8.8.8
EOF
fi

# 7. Daftarkan Service Systemd yang baru (Web Daemon)
echo -e "${YELLOW}[4/4] Memasang Service Background Daemon (Web Manager)...${NC}"
cat << 'EOF' > /etc/systemd/system/gost-web.service
[Unit]
Description=GOST Web Proxy Manager Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/gost-proxy
ExecStart=/opt/gost-proxy/gost_env/bin/uvicorn main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gost-web.service --now

IP_SERVER=$(curl -4 -s ifconfig.me || echo "IP-Server-Anda")

echo -e "\n${GREEN}✔ TRANSISI SELESAI & DAEMON WEB AKTIF!${NC}"
echo -e "${CYAN}Silakan akses dashboard installer / manager Anda di:${NC}"
echo -e "${YELLOW}👉 http://${IP_SERVER}:8080 👈${NC}"
echo -e "${CYAN}=================================================${NC}"
