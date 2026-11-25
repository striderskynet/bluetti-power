package com.striderskynet.bluetti;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanRecord;
import android.bluetooth.le.ScanResult;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.util.SparseArray;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * Cliente BLE mínimo para leer el estado de un BLUETTI (protocolo MODBUS sobre
 * las características ff01/ff02, con soporte del canal cifrado).
 *
 * <p>No usa ninguna librería externa: solo las APIs Bluetooth del sistema.</p>
 */
public final class BluettiClient {

    public static final UUID NOTIFY_UUID =
            UUID.fromString("0000ff01-0000-1000-8000-00805f9b34fb");
    public static final UUID WRITE_UUID =
            UUID.fromString("0000ff02-0000-1000-8000-00805f9b34fb");
    private static final UUID CCCD_UUID =
            UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    // Registros MODBUS del AC180P (misma tabla que la versión de Windows).
    private static final int REG_SOC = 102;
    private static final int REG_DEVICE_TYPE = 110;
    private static final int REG_SERIAL = 116;
    private static final int REG_DC_OUT = 140;
    private static final int REG_AC_OUT = 142;
    private static final int REG_DC_IN = 144;
    private static final int REG_AC_IN = 146;
    private static final int REG_GRID_VOLTAGE = 1314;

    private static final String[] MODEL_PREFIXES = {
            "AC2A", "AC50", "AC60", "AC70", "AC180", "AC200", "AC300", "AC500",
            "AP300", "EB3A", "EB70", "EL10", "EL30", "EL100", "EP500", "EP600",
            "EP760", "EP800", "EP2000", "Handsfree", "PR30", "PR100", "PBOX",
            "PBOX", "BLUETTI"
    };

    /** Un equipo BLUETTI detectado al escanear. */
    public static final class ScanHit {
        public final String address;
        public final String name;
        public final int rssi;
        public final int encryptedHint;

        ScanHit(String address, String name, int rssi, int encryptedHint) {
            this.address = address;
            this.name = name;
            this.rssi = rssi;
            this.encryptedHint = encryptedHint;
        }

        public String label() {
            String flag = encryptedHint == DeviceStore.HINT_ENCRYPTED ? " · cifrado"
                    : encryptedHint == DeviceStore.HINT_PLAIN ? " · sin cifrar" : "";
            return name + "  (" + address + ")  " + rssi + " dBm" + flag;
        }
    }

    private final Context context;
    private final LinkedBlockingQueue<byte[]> notifications = new LinkedBlockingQueue<>();
    private final ArrayDeque<byte[]> plainMessages = new ArrayDeque<>();
    private final ByteArrayOutputStream encryptedBuffer = new ByteArrayOutputStream();
    private final ByteArrayOutputStream rawKexBuffer = new ByteArrayOutputStream();
    private final BluettiCrypto crypto = new BluettiCrypto();

    private boolean encryptedMode;
    private boolean handshakeStarted;
    private boolean disconnected;

    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic notifyCharacteristic;
    private BluetoothGattCharacteristic writeCharacteristic;
    private volatile int mtu = 23;
    private int notificationsSeen;
    private String lastStage = "inicio";

    private volatile CountDownLatch connectLatch;
    private volatile CountDownLatch mtuLatch;
    private volatile CountDownLatch servicesLatch;
    private volatile CountDownLatch descriptorLatch;
    private volatile CountDownLatch writeLatch;
    private volatile boolean connectOk;
    private volatile boolean servicesOk;
    private volatile boolean descriptorOk;
    private volatile boolean writeOk;

    private BluettiClient(Context context) {
        this.context = context;
    }

    // ------------------------------------------------------------ API pública

    /** Escanea y devuelve los equipos BLUETTI visibles, ordenados por señal. */
    public static List<ScanHit> scan(Context context, long timeoutMs) throws IOException {
        ensureScanPermission(context);
        ensureConnectPermission(context);
        BluetoothManager manager = (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            throw new IOException("Bluetooth apagado");
        }
        BluetoothLeScanner scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) {
            throw new IOException("escáner Bluetooth no disponible");
        }

        final List<ScanHit> results = Collections.synchronizedList(new ArrayList<ScanHit>());
        final CountDownLatch finished = new CountDownLatch(1);
        ScanCallback callback = new ScanCallback() {
            @Override
            public void onScanResult(int callbackType, ScanResult result) {
                try {
                    ScanRecord record = result.getScanRecord();
                    String name = result.getDevice().getName();
                    if (name == null && record != null) {
                        name = record.getDeviceName();
                    }
                    if (name == null || !isBluettiName(name)) {
                        return;
                    }
                    String address = result.getDevice().getAddress();
                    if (address == null) {
                        return;
                    }
                    synchronized (results) {
                        for (ScanHit existing : results) {
                            if (existing.address.equalsIgnoreCase(address)) {
                                return;
                            }
                        }
                        results.add(new ScanHit(address, name, result.getRssi(), encryptionHint(record)));
                    }
                } catch (SecurityException ignored) {
                    // sin permiso de conexión no se puede leer el nombre
                }
            }

            @Override
            public void onScanFailed(int errorCode) {
                finished.countDown();
            }
        };

        try {
            scanner.startScan(callback);
        } catch (SecurityException exc) {
            throw new IOException("permisos de Bluetooth denegados");
        }
        try {
            finished.await(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            throw new IOException("escaneo interrumpido");
        } finally {
            try {
                scanner.stopScan(callback);
            } catch (SecurityException ignored) {
                // ignorado
            }
        }

        synchronized (results) {
            List<ScanHit> copy = new ArrayList<>(results);
            Collections.sort(copy, new java.util.Comparator<ScanHit>() {
                @Override
                public int compare(ScanHit first, ScanHit second) {
                    return Integer.compare(second.rssi, first.rssi);
                }
            });
            return copy;
        }
    }

    /** Lee una estación con reintentos y persiste el resultado. */
    public static synchronized Reading readNow(Context context, Device device) {
        Reading reading = new Reading();
        reading.time = System.currentTimeMillis();
        reading.address = device.address;
        reading.deviceType = device.model();

        if (DeviceStore.isDemo(context)) {
            Reading demo = demoReading(device);
            DeviceStore.saveState(context, device.id, demo);
            return demo;
        }

        String address = device.address;
        int hint = device.hint;
        String wantedName = device.name;
        String lastError = "no se pudo leer el equipo";

        for (int attempt = 0; attempt < 3; attempt++) {
            if (attempt == 1) {
                Logs.log(context, "Reintento de lectura de " + device.displayName() + "…");
                sleepQuietly(1200);
            } else if (attempt == 2 && wantedName != null && !wantedName.isEmpty()) {
                try {
                    ScanHit hit = scanFor(context, wantedName, 6000);
                    if (hit != null && !hit.address.equalsIgnoreCase(address)) {
                        Logs.log(context, "Dirección actualizada: " + address + " -> " + hit.address);
                        address = hit.address;
                        hint = hit.encryptedHint;
                        device.address = address;
                        DeviceStore.updateAddress(context, device.id, address);
                    }
                } catch (Exception scanExc) {
                    Logs.log(context, "Escaneo de recuperación fallido: " + friendly(scanExc));
                }
            }

            BluettiClient client = new BluettiClient(context);
            try {
                client.read(address, hint, reading);
                reading.error = null;
                reading.time = System.currentTimeMillis();
                reading.address = address;
                DeviceStore.saveState(context, device.id, reading);
                Logs.log(context, "OK " + device.displayName() + ": " + reading.percent + "%, "
                        + reading.totalOut() + " W" + (reading.encrypted ? " (cifrado)" : ""));
                return reading;
            } catch (Exception exc) {
                lastError = friendly(exc);
                Logs.log(context, "Fallo leyendo " + device.displayName() + " (intento "
                        + (attempt + 1) + "): " + lastError);
            } finally {
                client.close();
            }
        }

        reading.error = lastError;
        reading.time = System.currentTimeMillis();
        DeviceStore.saveState(context, device.id, reading);
        return reading;
    }

    /** Datos simulados por estación para probar la app y el widget sin equipo. */
    private static Reading demoReading(Device device) {
        long now = System.currentTimeMillis();
        int hash = Math.abs(device.id.hashCode());
        double phase = (now % 600000L) / 600000.0;
        Reading reading = new Reading();
        reading.percent = 40 + (hash % 50) + (int) Math.round(5 * Math.sin(phase * Math.PI * 2));
        if (reading.percent > 100) {
            reading.percent = 100;
        }
        reading.acOut = 80 + (hash % 200);
        reading.dcOut = 15;
        reading.acIn = 0;
        reading.dcIn = hash % 60;
        reading.gridVoltage = 0;
        reading.deviceType = device.model();
        reading.serialNumber = "DEMO" + (hash % 100000);
        reading.encrypted = true;
        reading.demo = true;
        reading.time = now;
        reading.address = device.address;
        return reading;
    }

    /** Busca por modelo/nombre y devuelve el equipo más cercano. */
    public static ScanHit scanFor(Context context, String wantedName, long timeoutMs) throws IOException {
        List<ScanHit> hits = scan(context, timeoutMs);
        String prefix = modelPrefix(wantedName);
        for (ScanHit hit : hits) {
            if (prefix.isEmpty() || hit.name.toUpperCase().startsWith(prefix.toUpperCase())) {
                return hit;
            }
        }
        return hits.isEmpty() ? null : hits.get(0);
    }

    // --------------------------------------------------------------- lectura

    private void read(String address, int hint, Reading reading) throws Exception {
        connect(address);
        boolean encrypted = establishChannel(hint);
        reading.encrypted = encrypted;

        byte[] soc = readRegister(REG_SOC, 1);
        reading.percent = Modbus.u16(soc, 0);
        if (reading.percent < 0 || reading.percent > 100) {
            throw new IOException("porcentaje de batería no válido");
        }
        byte[] typeBody = readRegister(REG_DEVICE_TYPE, 6);
        String deviceType = Modbus.swapString(typeBody).trim();
        if (!isValidDeviceType(deviceType)) {
            throw new IOException("modelo no reconocido: " + deviceType);
        }
        reading.deviceType = deviceType;
        try {
            reading.serialNumber = parseSerial(readRegister(REG_SERIAL, 4));
        } catch (IOException ignored) {
            reading.serialNumber = "";
        }
        reading.dcOut = Modbus.u16(readRegister(REG_DC_OUT, 1), 0);
        reading.acOut = Modbus.u16(readRegister(REG_AC_OUT, 1), 0);
        reading.dcIn = Modbus.u16(readRegister(REG_DC_IN, 1), 0);
        reading.acIn = Modbus.u16(readRegister(REG_AC_IN, 1), 0);
        try {
            byte[] gridBody = readRegister(REG_GRID_VOLTAGE, 1);
            reading.gridVoltage = Math.round(Modbus.u16(gridBody, 0) / 10f);
        } catch (IOException ignored) {
            reading.gridVoltage = -1;
        }
        reading.address = address;
        reading.time = System.currentTimeMillis();
    }

    /** Número de serie: 4 palabras u16 combinadas de menor a mayor peso. */
    private static String parseSerial(byte[] body) {
        if (body == null || body.length < 8) {
            return "";
        }
        long value = ((long) Modbus.u16(body, 0))
                | (((long) Modbus.u16(body, 2)) << 16)
                | (((long) Modbus.u16(body, 4)) << 32)
                | (((long) Modbus.u16(body, 6)) << 48);
        return Long.toString(value);
    }

    private void connect(String address) throws IOException {
        ensureConnectPermission(context);
        BluetoothManager manager = (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            throw new IOException("Bluetooth apagado");
        }

        BluetoothDevice device;
        try {
            device = adapter.getRemoteDevice(address);
        } catch (IllegalArgumentException exc) {
            throw new IOException("dirección Bluetooth no válida: " + address);
        }

        connectLatch = new CountDownLatch(1);
        connectOk = false;
        disconnected = false;
        try {
            gatt = device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE);
        } catch (SecurityException exc) {
            throw new IOException("permisos de Bluetooth denegados");
        }
        if (gatt == null) {
            throw new IOException("no se pudo crear la conexión BLE");
        }
        if (!await(connectLatch, 12000) || !connectOk) {
            throw new IOException("no se pudo conectar (¿equipo encendido y cerca?)");
        }

        mtuLatch = new CountDownLatch(1);
        mtu = 23;
        if (gatt.requestMtu(517)) {
            await(mtuLatch, 4000);
        }
        Logs.log(context, "Conectado; MTU=" + mtu);

        servicesLatch = new CountDownLatch(1);
        servicesOk = false;
        if (!gatt.discoverServices()) {
            throw new IOException("no se pudieron descubrir los servicios BLE");
        }
        if (!await(servicesLatch, 8000) || !servicesOk) {
            throw new IOException("descubrimiento de servicios incompleto");
        }

        notifyCharacteristic = null;
        writeCharacteristic = null;
        for (BluetoothGattService service : gatt.getServices()) {
            for (BluetoothGattCharacteristic characteristic : service.getCharacteristics()) {
                if (NOTIFY_UUID.equals(characteristic.getUuid())) {
                    notifyCharacteristic = characteristic;
                } else if (WRITE_UUID.equals(characteristic.getUuid())) {
                    writeCharacteristic = characteristic;
                }
            }
        }
        if (notifyCharacteristic == null || writeCharacteristic == null) {
            throw new IOException("el equipo no expone las características ff01/ff02");
        }
        Logs.log(context, "Servicios OK; ff01/ff02 encontrados");
        if (mtu < 149) {
            mtuLatch = new CountDownLatch(1);
            if (gatt.requestMtu(517)) {
                await(mtuLatch, 3000);
            }
            Logs.log(context, "MTU reintentado; ahora " + mtu);
        }

        if (!gatt.setCharacteristicNotification(notifyCharacteristic, true)) {
            throw new IOException("no se pudieron activar las notificaciones");
        }
        BluetoothGattDescriptor descriptor = notifyCharacteristic.getDescriptor(CCCD_UUID);
        if (descriptor == null) {
            throw new IOException("falta el descriptor CCCD");
        }
        boolean indicate = (notifyCharacteristic.getProperties()
                & BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0
                && (notifyCharacteristic.getProperties()
                & BluetoothGattCharacteristic.PROPERTY_NOTIFY) == 0;
        byte[] value = indicate
                ? BluetoothGattDescriptor.ENABLE_INDICATION_VALUE
                : BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE;

        descriptorLatch = new CountDownLatch(1);
        descriptorOk = false;
        boolean started;
        if (Build.VERSION.SDK_INT >= 33) {
            started = gatt.writeDescriptor(descriptor, value) == 0;
        } else {
            descriptor.setValue(value);
            started = gatt.writeDescriptor(descriptor);
        }
        if (!started || !await(descriptorLatch, 4000) || !descriptorOk) {
            throw new IOException("no se pudo activar el canal de notificaciones");
        }
        Logs.log(context, "Notificaciones activadas; esperando handshake…");
    }

    private boolean establishChannel(int hint) throws IOException {
        if (hint == DeviceStore.HINT_PLAIN) {
            encryptedMode = false;
            return false;
        }
        lastStage = "esperando challenge";
        long firstWait = hint == DeviceStore.HINT_ENCRYPTED ? 8000 : 2500;
        byte[] first = pollNotification(firstWait);
        if (first != null) {
            handleNotification(first);
        }
        if (handshakeStarted) {
            lastStage = "handshake";
            long deadline = System.currentTimeMillis() + 25000;
            while (!crypto.isReady() && System.currentTimeMillis() < deadline) {
                byte[] message = pollNotification(deadline - System.currentTimeMillis());
                if (message == null) {
                    break;
                }
                handleNotification(message);
            }
            encryptedMode = crypto.isReady();
        }
        if (encryptedMode) {
            Logs.log(context, "Canal cifrado listo (MTU=" + mtu + ")");
            return true;
        }
        if (hint == DeviceStore.HINT_ENCRYPTED) {
            String detail = "el equipo no completó el canal cifrado (etapa: " + lastStage
                    + ", MTU=" + mtu + ", notificaciones=" + notificationsSeen + ")";
            Logs.log(context, "ERROR: " + detail);
            throw new IOException(detail);
        }
        encryptedMode = false;
        return false;
    }

    private byte[] pollNotification(long timeoutMs) throws IOException {
        if (timeoutMs <= 0) {
            return null;
        }
        try {
            return notifications.poll(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            throw new IOException("lectura interrumpida");
        }
    }

    private void handleNotification(byte[] message) throws IOException {
        notificationsSeen++;
        if (message.length == 0) {
            disconnected = true;
            return;
        }
        try {
            if (BluettiCrypto.isPreKey(message)) {
                handshakeStarted = true;
                lastStage = "KEX crudo";
                Logs.log(context, "KEX crudo " + message.length + " bytes, tipo " + (message[2] & 0xFF));
                rawKexBuffer.write(message);
                byte[] buffer = rawKexBuffer.toByteArray();
                while (buffer.length >= 6) {
                    int dataLength = buffer[3] & 0xFF;
                    int expected = 6 + dataLength;
                    if (buffer.length < expected) {
                        break;
                    }
                    byte[] frame = Arrays.copyOfRange(buffer, 0, expected);
                    byte[] rest = Arrays.copyOfRange(buffer, expected, buffer.length);
                    rawKexBuffer.reset();
                    rawKexBuffer.write(rest);
                    byte[] reply = crypto.onRawMessage(frame);
                    if (reply != null) {
                        writeRaw(reply);
                    }
                    buffer = rawKexBuffer.toByteArray();
                }
                return;
            }
            if (handshakeStarted || encryptedMode) {
                encryptedBuffer.write(message);
                while (true) {
                    byte[] buffer = encryptedBuffer.toByteArray();
                    int expected = crypto.expectedEncryptedLength(buffer);
                    if (expected <= 0 || buffer.length < expected) {
                        break;
                    }
                    byte[] block = Arrays.copyOfRange(buffer, 0, expected);
                    byte[] rest = Arrays.copyOfRange(buffer, expected, buffer.length);
                    encryptedBuffer.reset();
                    encryptedBuffer.write(rest);
                    byte[] plain = crypto.decryptTransport(block);
                    if (BluettiCrypto.isPreKey(plain)) {
                        int type = plain[2] & 0xFF;
                        if (type == BluettiCrypto.TYPE_PEER_PUBKEY) {
                            // La clave pública del equipo también llega cifrada.
                            lastStage = "peer pubkey";
                            Logs.log(context, "Peer pubkey cifrada recibida; respondiendo");
                            byte[] reply = crypto.peerPubkeyReply(plain);
                            writeRaw(reply);
                        } else if (type == BluettiCrypto.TYPE_PUBKEY_ACCEPTED) {
                            lastStage = "clave aceptada";
                            Logs.log(context, "Clave aceptada; derivando clave de sesión");
                            crypto.onDecryptedMessage(plain);
                        } else {
                            Logs.log(context, "Mensaje KEX tipo " + type);
                        }
                    } else {
                        plainMessages.add(plain);
                    }
                }
            } else {
                plainMessages.add(message);
            }
        } catch (Exception exc) {
            String detail = "error de protocolo (" + lastStage + "): " + exc.getMessage();
            Logs.log(context, detail);
            throw new IOException(detail, exc);
        }
    }

    private byte[] readRegister(int address, int quantity) throws IOException {
        byte[] request = Modbus.readRequest(address, quantity);
        byte[] wire;
        try {
            wire = encryptedMode ? crypto.encryptTransport(request) : request;
        } catch (Exception exc) {
            throw new IOException("no se pudo cifrar la petición", exc);
        }
        writeRaw(wire);

        long deadline = System.currentTimeMillis() + 6000;
        ByteArrayOutputStream accumulated = new ByteArrayOutputStream();
        int expected = 5 + quantity * 2;
        while (System.currentTimeMillis() < deadline) {
            byte[] part = nextMessage(deadline);
            if (part == null) {
                break;
            }
            accumulated.write(part);
            byte[] all = accumulated.toByteArray();
            if (all.length >= expected) {
                byte[] frame = Arrays.copyOfRange(all, 0, expected);
                byte[] rest = Arrays.copyOfRange(all, expected, all.length);
                if (rest.length > 0) {
                    plainMessages.addFirst(rest);
                }
                byte[] body = Modbus.parseReadResponse(frame, quantity);
                if (body == null) {
                    throw new IOException("respuesta MODBUS inválida");
                }
                return body;
            }
        }
        throw new IOException("sin respuesta del equipo (registro " + address + ")");
    }

    private byte[] nextMessage(long deadline) throws IOException {
        while (System.currentTimeMillis() < deadline) {
            byte[] queued = plainMessages.poll();
            if (queued != null) {
                return queued;
            }
            byte[] notification = pollNotification(deadline - System.currentTimeMillis());
            if (notification == null) {
                return null;
            }
            handleNotification(notification);
        }
        return null;
    }

    // ------------------------------------------------------------- escritura

    private void writeRaw(byte[] data) throws IOException {
        if (gatt == null || writeCharacteristic == null) {
            throw new IOException("conexión BLE cerrada");
        }
        Logs.log(context, "→ " + data.length + " bytes" + (data.length > mtu - 3 ? " (mayor que MTU-3)" : ""));
        writeLatch = new CountDownLatch(1);
        writeOk = false;
        boolean started;
        if (Build.VERSION.SDK_INT >= 33) {
            started = gatt.writeCharacteristic(
                    writeCharacteristic, data, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
        } else {
            writeCharacteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            writeCharacteristic.setValue(data);
            started = gatt.writeCharacteristic(writeCharacteristic);
        }
        if (!started) {
            Logs.log(context, "No se pudo iniciar la escritura (" + data.length + " bytes)");
            throw new IOException("no se pudo iniciar la escritura BLE");
        }
        if (!await(writeLatch, 6000) || !writeOk) {
            Logs.log(context, "Escritura BLE sin éxito (" + data.length + " bytes)");
            throw new IOException("escritura BLE fallida");
        }
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
        }
    }

    private void close() {
        if (gatt != null) {
            try {
                gatt.disconnect();
            } catch (Exception ignored) {
                // ignorado
            }
            try {
                gatt.close();
            } catch (Exception ignored) {
                // ignorado
            }
            gatt = null;
        }
    }

    private static boolean await(CountDownLatch latch, long timeoutMs) {
        try {
            return latch.await(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    // -------------------------------------------------------------- callbacks

    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                connectOk = status == BluetoothGatt.GATT_SUCCESS;
                if (connectLatch != null) {
                    connectLatch.countDown();
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                connectOk = false;
                disconnected = true;
                if (connectLatch != null) {
                    connectLatch.countDown();
                }
                notifications.offer(new byte[0]);
            }
        }

        @Override
        public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
            BluettiClient.this.mtu = mtu;
            if (mtuLatch != null) {
                mtuLatch.countDown();
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt gatt, int status) {
            servicesOk = status == BluetoothGatt.GATT_SUCCESS;
            if (servicesLatch != null) {
                servicesLatch.countDown();
            }
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt gatt, BluetoothGattDescriptor descriptor, int status) {
            descriptorOk = status == BluetoothGatt.GATT_SUCCESS;
            if (descriptorLatch != null) {
                descriptorLatch.countDown();
            }
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            writeOk = status == BluetoothGatt.GATT_SUCCESS;
            if (writeLatch != null) {
                writeLatch.countDown();
            }
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic,
                                            byte[] value) {
            if (value != null) {
                notifications.offer(value.clone());
            }
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic) {
            byte[] value = characteristic.getValue();
            if (value != null) {
                notifications.offer(value.clone());
            }
        }
    };

    // ----------------------------------------------------------- utilidades

    private static String friendly(Exception exc) {
        String message = exc.getMessage();
        if (message == null || message.isEmpty()) {
            message = exc.getClass().getSimpleName();
        }
        return message;
    }

    private static boolean isBluettiName(String name) {
        String upper = name.toUpperCase();
        for (String prefix : MODEL_PREFIXES) {
            if (upper.startsWith(prefix.toUpperCase())) {
                return true;
            }
        }
        return false;
    }

    private static boolean isValidDeviceType(String deviceType) {
        if (deviceType == null || deviceType.length() < 3) {
            return false;
        }
        return isBluettiName(deviceType);
    }

    private static String modelPrefix(String name) {
        if (name == null || name.trim().isEmpty()) {
            return "";
        }
        String trimmed = name.trim();
        return trimmed.length() > 5 ? trimmed.substring(0, 5) : trimmed;
    }

    private static int encryptionHint(ScanRecord record) {
        if (record == null) {
            return DeviceStore.HINT_UNKNOWN;
        }
        SparseArray<byte[]> manufacturer = record.getManufacturerSpecificData();
        if (manufacturer == null) {
            return DeviceStore.HINT_UNKNOWN;
        }
        boolean plain = false;
        for (int i = 0; i < manufacturer.size(); i++) {
            byte[] data = manufacturer.valueAt(i);
            if (data == null) {
                continue;
            }
            if (containsAscii(data, "BLUETTF")) {
                return DeviceStore.HINT_ENCRYPTED;
            }
            if (containsAscii(data, "BLUETTI")) {
                plain = true;
            }
        }
        return plain ? DeviceStore.HINT_PLAIN : DeviceStore.HINT_UNKNOWN;
    }

    private static boolean containsAscii(byte[] haystack, String needle) {
        byte[] pattern = needle.getBytes();
        outer:
        for (int i = 0; i + pattern.length <= haystack.length; i++) {
            for (int j = 0; j < pattern.length; j++) {
                if (haystack[i + j] != pattern[j]) {
                    continue outer;
                }
            }
            return true;
        }
        return false;
    }

    private static void ensureScanPermission(Context context) {
        if (Build.VERSION.SDK_INT >= 31) {
            if (context.checkSelfPermission(android.Manifest.permission.BLUETOOTH_SCAN)
                    != PackageManager.PERMISSION_GRANTED) {
                throw new SecurityException("permiso BLUETOOTH_SCAN denegado");
            }
        } else if (context.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            throw new SecurityException("permiso de ubicación denegado (necesario para escanear)");
        }
    }

    private static void ensureConnectPermission(Context context) {
        if (Build.VERSION.SDK_INT >= 31) {
            if (context.checkSelfPermission(android.Manifest.permission.BLUETOOTH_CONNECT)
                    != PackageManager.PERMISSION_GRANTED) {
                throw new SecurityException("permiso BLUETOOTH_CONNECT denegado");
            }
        }
    }
}

