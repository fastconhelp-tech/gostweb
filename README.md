# 🚀 GOST Proxy Web Manager V6.0.2

GOST Proxy Web Manager adalah sistem manajemen proxy multi-zone berbasis **FastAPI** dengan **Dashboard Web modern** (TailwindCSS). Sistem ini menggantikan versi CLI lama menjadi antarmuka web yang interaktif, mendukung failover otomatis, pemantauan status real-time, dan integrasi bot Telegram.

## ✨ Fitur Utama
* **Web Dashboard**: Monitoring CPU, RAM, Ping, dan log proxy secara real-time.
* **Multi-Zone Port Management**: Pisahkan port proxy ke dalam zona yang berbeda.
* **Auto-Failover**: Otomatis mengganti proxy yang mati (LOS) dengan cadangan di zona yang sama.
* **Bulk Import**: Tambahkan ratusan proxy sekaligus dari dashboard web.
* **Telegram Bot Alert**: Notifikasi otomatis saat IP proxy mati atau pulih.
* **FindIP Intelligence**: Deteksi IP kotor (Dirty IP/VPN/Tor) secara otomatis.

## 🛠️ Instalasi Otomatis (Satu Baris)
Jalankan perintah ini di terminal server Ubuntu/Debian Anda (login sebagai `root`):

```bash
bash <(curl -s [https://raw.githubusercontent.com/USERNAME_GITHUB_ANDA/gost-web-manager/main/installer.sh](https://raw.githubusercontent.com/USERNAME_GITHUB_ANDA/gost-web-manager/main/installer.sh))
