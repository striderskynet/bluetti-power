#!/usr/bin/env bash
# Instala el monitor del BLUETTI AC180P en Raspberry Pi OS Lite (arm64).
#
#   sudo ./install.sh
#   sudo /opt/bluetti-monitor/venv/bin/python /opt/bluetti-monitor/bluetti_pi.py setup --config /etc/bluetti-monitor/config.json
#   sudo systemctl start bluetti-monitor
#
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Ejecuta este script con sudo." >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/opt/bluetti-monitor
CONF_DIR=/etc/bluetti-monitor
STATE_DIR=/var/lib/bluetti-monitor

echo "==> Instalando paquetes del sistema"
apt-get update
apt-get install -y python3-venv python3-pip bluetooth bluez rfkill

echo "==> Copiando aplicación a $APP_DIR"
install -d "$APP_DIR" "$CONF_DIR" "$STATE_DIR"
install -m 644 "$HERE/bluetti_protocol.py" "$APP_DIR/"
install -m 644 "$HERE/bluetti_pi.py" "$APP_DIR/"
install -m 644 "$HERE/requirements-raspi.txt" "$APP_DIR/"

echo "==> Creando entorno virtual e instalando dependencias"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements-raspi.txt"

if [ ! -f "$CONF_DIR/config.json" ]; then
    echo "==> Creando configuración inicial"
    cat > "$CONF_DIR/config.json" <<'JSON'
{
  "address": "",
  "name": "",
  "encrypted_hint": null,
  "interval_seconds": 60,
  "http_host": "0.0.0.0",
  "http_port": 8099,
  "state_file": "/var/lib/bluetti-monitor/state.json",
  "request_timeout": 50.0,
  "log_level": "INFO"
}
JSON
    chmod 600 "$CONF_DIR/config.json"
fi

echo "==> Instalando servicio systemd"
install -m 644 "$HERE/bluetti-monitor.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bluetti-monitor

rfkill unblock bluetooth 2>/dev/null || true

echo ""
echo "Instalación terminada."
echo ""
echo "1) Enciende el AC180P y busca su dirección Bluetooth:"
echo "   sudo $APP_DIR/venv/bin/python $APP_DIR/bluetti_pi.py scan"
echo ""
echo "2) Guarda la configuración (detecta el primer BLUETTI que encuentre):"
echo "   sudo $APP_DIR/venv/bin/python $APP_DIR/bluetti_pi.py setup --config $CONF_DIR/config.json"
echo ""
echo "3) Arranca el servicio:"
echo "   sudo systemctl start bluetti-monitor && systemctl status bluetti-monitor"
echo ""
echo "4) Comprueba el estado por HTTP:"
echo "   curl http://localhost:8099/status"
echo ""
echo "Para desinstalar: sudo systemctl disable --now bluetti-monitor && sudo rm -rf $APP_DIR $CONF_DIR $STATE_DIR /etc/systemd/system/bluetti-monitor.service"
