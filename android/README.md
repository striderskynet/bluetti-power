# BluettiWidget — app Android + widgets para estaciones BLUETTI

App Android **ultraligera** (APK de ~130 KB, sin dependencias ni Google Play
Services) que se conecta por Bluetooth LE a una o varias estaciones BLUETTI
(AC180P y familia V2), y muestra su estado en la app y en **widgets** de la
pantalla de inicio.

- **Varias estaciones** a la vez: añade todas las que quieras y consulta cada
  una por separado.
- **Un widget por estación**: al añadir el widget eliges qué estación muestra;
  puedes tener varios widgets (uno por equipo).
- **Intervalo configurable** de actualización automática: **1, 2, 5, 10, 15,
  30 o 60 minutos** (mínimo 1 minuto).
- **Widget completo (4×3) con iconos**: además de carga, consumo, estado y
  barra de batería, muestra **entrada solar, entrada de red, voltaje de red,
  salida AC, salida DC** y **energía restante/total (Wh)**.
- **Más información por estación**: modelo, nº de serie, dirección BLE, canal
  cifrado, salida AC/DC, entrada de red/solar, voltaje de red, capacidad y
  energía restante, estado y última lectura.
- Renombrar y quitar estaciones, **Acerca de**, modo demo, registro con
  **Compartir**.
- Servicio en primer plano para que las actualizaciones no se duerman, con
  notificación-resumen y acciones *Actualizar/Detener*.

Sin nube, sin cuentas, sin telemetría. Todo se queda en el móvil.

![Vista previa del widget](../assets/android-widget.png)

## Instalación

1. Descarga `dist/BluettiWidget-v0.4.1.apk` (o desde el release de GitHub) y
   ábrelo en el móvil; acepta **instalar apps de origen desconocido**.
2. Concede permisos: **Dispositivos cercanos**, **Notificaciones** y, en
   Android 11 o inferior, **Ubicación**.
3. APK firmado con clave de depuración (no es para Google Play). Para
   actualizar encima conserva el mismo APK/keystore.

## Uso

### Añadir estaciones

1. Enciende la estación y cierra la app oficial de BLUETTI en el móvil (solo
   admite una conexión BLE a la vez).
2. **Añadir estación** → elige el equipo en la lista. Se añade a la lista y se
   lee al momento.
3. Repite para cada estación.

Cada tarjeta muestra nombre (modelo + últimos dígitos o el alias que le pongas),
dirección, **%**, **consumo W**, estado, antigüedad y desglose
`AC · DC · entrada`. Botones: **Leer**, **Datos**, **Nombre**, **Quitar**.

### Ver más información

**Datos** abre el detalle de la estación: modelo, **número de serie**,
dirección BLE, conexión cifrada/sin cifrar, salida AC/DC y total, entrada
AC/solar y total, estado y fecha/hora de la última lectura (con su antigüedad).

### Actualización automática

En la tarjeta superior elige **Cada** (1–60 min) y pulsa **Activar
actualización automática**. Aparece una notificación persistente (obligatoria
en Android) con un resumen de las estaciones, botones *Actualizar* y *Detener*.
El servicio recorre las estaciones una a una; si tienes varias, cada ciclo
tardará unos segundos más por equipo.

### Widgets

1. Mantén pulsado el escritorio → **Widgets** → **Bluetti**.
2. Elige **qué estación** muestra ese widget (puedes añadir uno por estación).
3. El widget (4×3, con iconos) muestra:
   - **% de carga** con barra de batería y color según nivel.
   - **Consumo total** (salida AC + DC).
   - **Entrada solar** (W) y **entrada de red** (W).
   - **Voltaje de red** (V) cuando hay entrada de red activa.
   - **Salida AC** y **salida DC** (W).
   - **Energía restante** (aprox.) y capacidad total (Wh).
   - Estado, nombre de la estación y antigüedad de la lectura.
4. Se actualiza con el intervalo configurado. Tócalo para abrir la app.

### Más datos y "Acerca de"

El botón **Datos** de cada estación muestra modelo, nº de serie, dirección BLE,
cifrado, salidas/entradas, **voltaje de red**, **capacidad** y **energía
restante**, estado y última lectura. El botón **Acerca de** muestra la versión,
la autoría y los créditos del proyecto.

### Modo demo

Activa **Modo demo** para probar la app y los widgets sin equipo (datos
simulados por estación).

## Límites y notas

- El AC180P admite **una conexión BLE a la vez**: mientras se lee una estación,
  la app oficial no puede conectar con ella; y tu app no puede leer dos a la
  vez (las lee en secuencia).
- Android puede matar el servicio en algunos fabricantes (Xiaomi, Huawei…).
  Desactiva la optimización de batería para **Bluetti** si los widgets dejan de
  actualizarse.
- El intervalo es de reloj: cada ciclo incluye los segundos de lectura; con
  varias estaciones, el ciclo real puede superar ligeramente el intervalo.
- Tras reiniciar el móvil se intenta reanudar el servicio si estaba activo.
- En Android 11 o inferior el **escaneo** puede requerir ubicación activada.

## Actualizar desde versiones anteriores

- **v0.4.1**: compatibilidad del widget: iconos en PNG (no vectores), PreviewBar con estilo explícito, sin previewLayout ni View separador. Corrige el error «Couldn't load the widget» en algunos launchers.
- **v0.4**: el widget (4×3) añade entrada solar, entrada de red, voltaje de red,
  salidas AC/DC y energía restante/total con iconos; botón **Acerca de**.
  La energía restante es aproximada (capacidad del modelo × % de batería).
- **v0.3**: multiestación, widgets por estación, intervalo 1–60 min, widget
  rediseñado, detalles con nº de serie. La estación de la v0.2 se migra
  automáticamente; los widgets antiguos se asignan a la primera estación
  (puedes quitarlos y volver a añadirlos para elegir otra).
  Tras instalar, **abre la app una vez** para que se actualicen los widgets y
  el servicio.
- **v0.2**: corrigió el handshake cifrado (clave pública del equipo cifrada).
- **v0.1**: primera versión.

## Diagnóstico

Botón **Registro**: incluye conexión, MTU negociado, cada etapa del handshake,
lecturas y errores. Botones **Compartir** y **Limpiar**.

| Mensaje | Causa / solución |
| --- | --- |
| `permisos de Bluetooth denegados` | Concede "Dispositivos cercanos". |
| `no se pudo conectar` | Estación apagada, lejos o conectada a otro dispositivo. |
| `el equipo no completó el canal cifrado` | Handshake interrumpido; acerca el móvil y reintenta (la app ya reintenta 3 veces). |
| `sin respuesta del equipo (registro N)` | Conexión cortada a mitad de lectura (señal débil). |
| Widget `sin estación` | Quita el widget y vuelve a añadirlo eligiendo estación (o añade una estación). |

## Compilar

Sin Gradle ni Android Studio. Toolchain mínimo (JDK 17 + platform 34 +
build-tools 34):

```powershell
.\setup_toolchain.ps1   # una sola vez
.\build.ps1             # autoprueba + compila + firma -> dist\BluettiWidget.apk
```

El build ejecuta antes la **autoprueba del protocolo** (MODBUS, AES, ECDH,
firmas y un handshake cifrado simulado).

### Estructura

```
app/src/main/java/com/striderskynet/bluetti/
  MainActivity.java          lista de estaciones, ajustes y detalle
  Device.java                estación configurada
  DeviceStore.java           persistencia: estaciones, estados, intervalo, widgets
  BluettiClient.java         BLE: escaneo, conexión, handshake y lecturas
  BluettiCrypto.java         handshake cifrado (ECDH P-256 + AES-CBC)
  Modbus.java                tramas MODBUS RTU y CRC16
  PollService.java           servicio en primer plano multiestación
  WidgetProvider.java        widgets (RemoteViews) por estación
  WidgetConfigureActivity.java  selector de estación al añadir el widget
  BootReceiver.java          reanudar tras reinicio
  Logs.java                  registro local compartible
app/src/main/res/            layouts, widget, barra de batería, iconos
tools/ProtocolSelfTest.java  autoprueba del protocolo
```

## Créditos

Protocolo y criptografía basados en
[`bluetti-bt-lib`](https://github.com/Patrick762/bluetti-bt-lib) (MIT) y en el
trabajo original de `bluetti_mqtt` (warhammerkid, nhurman, jesherman). Proyecto
no oficial, sin relación con BLUETTI.


