# Bluetti Pi — monitor headless para Raspberry Pi

Daemon para **Raspberry Pi OS Lite 64-bit (arm64, Debian 13 "trixie",
Python 3.13)** que se conecta por Bluetooth LE al BLUETTI AC180P, lee la carga
y el consumo, y los publica por **HTTP JSON** y en un **archivo de estado**.
Sin interfaz gráfica, sin nube, sin dependencias pesadas.

- **Cada N segundos** (60 por defecto) lee: % de carga, consumo (AC+DC),
  entrada (red/solar), estado y modelo.
- **`GET /status`** devuelve el estado en JSON (para Home Assistant, scripts,
  Grafana…). **`GET /health`** devuelve `ok` y antigüedad del dato.
- **Archivo de estado** opcional (`state.json`) que se reescribe de forma
  atómica tras cada lectura.
- **systemd**: arranca al boot, se reinicia si falla, logs en journald.
- Usa **el mismo protocolo validado** que las versiones Windows/Android
  (MODBUS sobre BLE + handshake cifrado ECDH/AES), pero **autocontenido**: solo
  `bleak` + `cryptography` (wheels para aarch64, sin compilador).

> Probado contra un AC180P real (canal BLE cifrado) desde Linux/Windows usando
> exactamente este código: lectura en ~9 s (91 %, 74 W). En la Raspberry el
> backend BLE es BlueZ en vez de WinRT; el resto es idéntico.

## Instalación

Requisitos: Raspberry Pi 3/4/5 con Bluetooth, Raspberry Pi OS Lite **64-bit**
(ya trae Python 3.13), el AC180P encendido y cerca.

```bash
# copia la carpeta raspi/ a la Raspberry (scp, git clone, etc.)
cd raspi
sudo ./install.sh
```

El script instala `python3-venv`/`bluez`, crea el venv en
`/opt/bluetti-monitor`, copia la app, crea
`/etc/bluetti-monitor/config.json` y deja el servicio `bluetti-monitor`
habilitado (aún sin arrancar, para configurarlo antes).

## Configurar el equipo

1. Enciende el AC180P y escanea:

   ```bash
   sudo /opt/bluetti-monitor/venv/bin/python /opt/bluetti-monitor/bluetti_pi.py scan
   ```

2. Guarda el dispositivo detectado (elige el primero si hay varios):

   ```bash
   sudo /opt/bluetti-monitor/venv/bin/python /opt/bluetti-monitor/bluetti_pi.py setup \
       --config /etc/bluetti-monitor/config.json
   ```

3. Arranca el servicio y comprueba:

   ```bash
   sudo systemctl start bluetti-monitor
   systemctl status bluetti-monitor
   curl http://localhost:8099/status
   journalctl -u bluetti-monitor -f        # logs en vivo
   ```

## Configuración

`/etc/bluetti-monitor/config.json`:

| Clave | Por defecto | Descripción |
| --- | --- | --- |
| `address` | `""` | Dirección BLE del AC180P (`AA:BB:CC:DD:EE:FF`) |
| `name` | `""` | Nombre anunciado (`AC180P…`), para reencontrarlo si cambia la dirección |
| `encrypted_hint` | `null` | `true`/`false` para forzar; `null` lo autodetecta |
| `interval_seconds` | `60` | Segundos entre lecturas (10–3600) |
| `http_host` | `"0.0.0.0"` | Interfaz del servidor HTTP (solo lectura) |
| `http_port` | `8099` | Puerto HTTP; `0` lo desactiva |
| `state_file` | `""` | Ruta del JSON de estado (vacío = no escribir archivo) |
| `request_timeout` | `50` | Timeout de una lectura completa (segundos) |
| `log_level` | `"INFO"` | `DEBUG` para diagnóstico |

Tras editar el archivo: `sudo systemctl restart bluetti-monitor`.

## API HTTP

```
GET /status   -> estado completo
GET /health   -> {"ok": true/false, "age_seconds": 1.3}
```

Ejemplo de `/status`:

```json
{
  "ok": true,
  "battery_percent": 91,
  "output_watts": 74,
  "ac_output_watts": 54,
  "dc_output_watts": 20,
  "input_watts": 26,
  "ac_input_watts": 0,
  "dc_input_watts": 26,
  "state": "entrada y salida",
  "device_type": "AC180P",
  "encrypted": true,
  "address": "FF:87:70:83:C6:37",
  "error": null,
  "updated_at": "2026-11-25T17:29:03+00:00",
  "age_seconds": 0.2,
  "interval_seconds": 60
}
```

Si una lectura falla, se publica `ok:false`, `error` y `stale:true`, pero se
conservan los últimos valores buenos y su antigüedad (`age_seconds` calculado
desde la última lectura correcta).

### Home Assistant (sensor REST)

```yaml
sensor:
  - platform: rest
    name: Bluetti AC180P
    resource: http://IP_DE_LA_RASPI:8099/status
    value_template: "{{ value_json.battery_percent }}"
    unit_of_measurement: "%"
    scan_interval: 60
    json_attributes:
      - output_watts
      - input_watts
      - ac_output_watts
      - dc_output_watts
      - ac_input_watts
      - dc_input_watts
      - state
      - encrypted
      - error
      - age_seconds
```

## Comandos

```bash
PY=/opt/bluetti-monitor/venv/bin/python
APP=/opt/bluetti-monitor/bluetti_pi.py
sudo $PY $APP scan                 # escanear equipos
sudo $PY $APP setup                # detectar y guardar configuración
sudo $PY $APP read                 # lectura puntual legible
sudo $PY $APP read --json          # lectura puntual en JSON
sudo $PY $APP run                  # daemon (lo lanza systemd)
```

## Servicio systemd

```bash
sudo systemctl enable --now bluetti-monitor   # arrancar y habilitar en boot
sudo systemctl restart bluetti-monitor
journalctl -u bluetti-monitor -f
```

## Problemas típicos

| Síntoma | Solución |
| --- | --- |
| `no se encontró ningún BLUETTI` | Enciende el equipo, acércalo y comprueba `rfkill list` / `bluetoothctl show`; `sudo rfkill unblock bluetooth`. |
| `conexión BLE perdida` / timeouts | Señal débil o el equipo está conectado a otro dispositivo (solo admite una conexión BLE). Cierra la app del móvil y reintenta. |
| Funcionaba y dejó de encontrar el equipo | La dirección BLE cambió: `bluetti-pi setup` de nuevo, o rellena `name` en la config para que lo busque por nombre. |
| `permission denied` en D-Bus | El servicio corre como root (necesario para BlueZ en headless sin sesión). Comprueba `systemctl status bluetooth`. |
| El puerto 8099 está ocupado | Cambia `http_port` en la config. |
| Quiero ver el tráfico | Sube `log_level` a `DEBUG` y `journalctl -u bluetti-monitor -f`. |

## Desinstalar

```bash
sudo systemctl disable --now bluetti-monitor
sudo rm -rf /opt/bluetti-monitor /etc/bluetti-monitor /var/lib/bluetti-monitor
sudo rm /etc/systemd/system/bluetti-monitor.service
sudo systemctl daemon-reload
```

## Estructura

```
raspi/
  bluetti_protocol.py        BLE + MODBUS + handshake cifrado (autocontenido)
  bluetti_pi.py              CLI, daemon, HTTP JSON y archivo de estado
  test_protocol.py           autopruebas (MODBUS, AES, ECDH, handshake simulado)
  bluetti-monitor.service    unidad systemd
  install.sh                 instalador para Raspberry Pi OS Lite
  requirements-raspi.txt     bleak + cryptography
```

### Pruebas

```bash
python3 -m unittest raspi.test_protocol -v     # desde la raíz del repo
```

Incluye vectores generados con la implementación de referencia y un handshake
cifrado completo simulado (incluido que la clave pública del equipo llega
**cifrada** con la clave temporal).

## Créditos

Protocolo y criptografía basados en
[`bluetti-bt-lib`](https://github.com/Patrick762/bluetti-bt-lib) (MIT) y en el
trabajo original de `bluetti_mqtt` (warhammerkid, nhurman, jesherman). Proyecto
no oficial, sin relación con BLUETTI.
