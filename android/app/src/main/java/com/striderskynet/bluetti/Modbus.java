package com.striderskynet.bluetti;

/** Tramas MODBUS RTU sobre BLE del protocolo BLUETTI (esclavo 0x01, función 0x03). */
public final class Modbus {

    private Modbus() {
    }

    public static int crc16(byte[] data, int length) {
        int crc = 0xFFFF;
        for (int i = 0; i < length; i++) {
            crc ^= data[i] & 0xFF;
            for (int bit = 0; bit < 8; bit++) {
                if ((crc & 1) != 0) {
                    crc = (crc >> 1) ^ 0xA001;
                } else {
                    crc >>= 1;
                }
            }
        }
        return crc & 0xFFFF;
    }

    /** Petición de lectura: 01 03 <addr BE> <cantidad BE> <crc LE>. */
    public static byte[] readRequest(int address, int quantity) {
        byte[] cmd = new byte[8];
        cmd[0] = 0x01;
        cmd[1] = 0x03;
        cmd[2] = (byte) ((address >> 8) & 0xFF);
        cmd[3] = (byte) (address & 0xFF);
        cmd[4] = (byte) ((quantity >> 8) & 0xFF);
        cmd[5] = (byte) (quantity & 0xFF);
        int crc = crc16(cmd, 6);
        cmd[6] = (byte) (crc & 0xFF);
        cmd[7] = (byte) ((crc >> 8) & 0xFF);
        return cmd;
    }

    /**
     * Valida y extrae el cuerpo de una respuesta de lectura.
     *
     * @return cuerpo (2 bytes por registro) o null si la trama no es válida.
     */
    public static byte[] parseReadResponse(byte[] response, int quantity) {
        if (response == null || response.length < 5) {
            return null;
        }
        if ((response[0] & 0xFF) != 0x01 || (response[1] & 0xFF) != 0x03) {
            return null;
        }
        int byteCount = response[2] & 0xFF;
        if (byteCount != quantity * 2 || response.length != byteCount + 5) {
            return null;
        }
        int crc = crc16(response, response.length - 2);
        int received = (response[response.length - 2] & 0xFF)
                | ((response[response.length - 1] & 0xFF) << 8);
        if (crc != received) {
            return null;
        }
        byte[] body = new byte[byteCount];
        System.arraycopy(response, 3, body, 0, byteCount);
        return body;
    }

    public static int u16(byte[] body, int index) {
        return ((body[index] & 0xFF) << 8) | (body[index + 1] & 0xFF);
    }

    /** Cadena tipo "swap string" usada para el modelo (bytes intercambiados por palabra). */
    public static String swapString(byte[] body) {
        byte[] swapped = body.clone();
        for (int i = 0; i + 1 < swapped.length; i += 2) {
            byte tmp = swapped[i];
            swapped[i] = swapped[i + 1];
            swapped[i + 1] = tmp;
        }
        int length = swapped.length;
        while (length > 0 && swapped[length - 1] == 0) {
            length--;
        }
        return new String(swapped, 0, length);
    }
}
