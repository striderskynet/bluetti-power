package com.striderskynet.bluetti;

import java.security.MessageDigest;
import java.util.Arrays;

/** Utilidades de bytes, hexadecimal y MD5. */
public final class Hex {

    private static final char[] DIGITS = "0123456789abcdef".toCharArray();

    private Hex() {
    }

    public static byte[] fromHex(String text) {
        String value = text == null ? "" : text.replace(" ", "").trim();
        if ((value.length() & 1) != 0) {
            throw new IllegalArgumentException("hex impar: " + value);
        }
        byte[] out = new byte[value.length() / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(value.substring(i * 2, i * 2 + 2), 16);
        }
        return out;
    }

    public static String toHex(byte[] data) {
        if (data == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder(data.length * 2);
        for (byte b : data) {
            sb.append(DIGITS[(b >> 4) & 0x0F]).append(DIGITS[b & 0x0F]);
        }
        return sb.toString();
    }

    public static String toHex(byte[] data, int offset, int length) {
        return toHex(Arrays.copyOfRange(data, offset, offset + length));
    }

    public static byte[] concat(byte[]... parts) {
        int total = 0;
        for (byte[] part : parts) {
            total += part.length;
        }
        byte[] out = new byte[total];
        int position = 0;
        for (byte[] part : parts) {
            System.arraycopy(part, 0, out, position, part.length);
            position += part.length;
        }
        return out;
    }

    public static byte[] xor(byte[] a, byte[] b) {
        if (a.length != b.length) {
            throw new IllegalArgumentException("xor de longitudes distintas");
        }
        byte[] out = new byte[a.length];
        for (int i = 0; i < a.length; i++) {
            out[i] = (byte) (a[i] ^ b[i]);
        }
        return out;
    }

    public static byte[] md5(byte[] data) {
        try {
            return MessageDigest.getInstance("MD5").digest(data);
        } catch (Exception exc) {
            throw new IllegalStateException("MD5 no disponible", exc);
        }
    }

    public static byte[] reversed(byte[] data) {
        byte[] out = new byte[data.length];
        for (int i = 0; i < data.length; i++) {
            out[i] = data[data.length - 1 - i];
        }
        return out;
    }

    /** Checksum del protocolo BLUETTI: suma de bytes del cuerpo, 2 bytes big endian. */
    public static byte[] checksum(byte[] body) {
        int sum = 0;
        for (byte b : body) {
            sum += b & 0xFF;
        }
        return new byte[] {(byte) ((sum >> 8) & 0xFF), (byte) (sum & 0xFF)};
    }

    /** Rellena a la izquierda con ceros hasta 32 bytes (coordenadas de curva). */
    public static byte[] padLeft(byte[] value, int length) {
        if (value.length == length) {
            return value;
        }
        if (value.length > length) {
            return Arrays.copyOfRange(value, value.length - length, value.length);
        }
        byte[] out = new byte[length];
        System.arraycopy(value, 0, out, length - value.length, value.length);
        return out;
    }
}
