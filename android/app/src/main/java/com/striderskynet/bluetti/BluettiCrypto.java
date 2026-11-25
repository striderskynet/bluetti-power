package com.striderskynet.bluetti;

import java.io.ByteArrayOutputStream;
import java.math.BigInteger;
import java.security.AlgorithmParameters;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.SecureRandom;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import java.security.spec.ECParameterSpec;
import java.security.spec.ECPoint;
import java.security.spec.ECPrivateKeySpec;
import java.security.spec.ECPublicKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Arrays;

import javax.crypto.Cipher;
import javax.crypto.KeyAgreement;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * Handshake cifrado del canal BLE de BLUETTI (ECDH P-256 + AES-CBC).
 *
 * <p>Port en Java de {@code bluetti_bt_lib/bluetooth/encryption.py}
 * (MIT, Patrick762) basado a su vez en el trabajo de nhurman/warhammerkid.</p>
 */
public final class BluettiCrypto {

    public static final byte[] MAGIC = {0x2A, 0x2A};

    public static final int TYPE_CHALLENGE = 1;
    public static final int TYPE_CHALLENGE_ACCEPTED = 3;
    public static final int TYPE_PEER_PUBKEY = 4;
    public static final int TYPE_PUBKEY_ACCEPTED = 6;

    static final byte[] LOCAL_AES_KEY = Hex.fromHex("459FC535808941F17091E0993EE3E93D");
    static final byte[] PRIVATE_KEY_L1 = Hex.fromHex(
            "4F19A16E3E87BDD9BD24D3E5495B88041511943CBC8B969ADE9641D0F56AF337");
    static final byte[] PUBLIC_KEY_K2 = Hex.fromHex(
            "3059301306072a8648ce3d020106082a8648ce3d03010703420004A73ABF5D2232C8C1C72E68304343C272495E3A8FD6F30EA96DE2F4B3CE60B251EE21AC667CF8A71E18B46B664EAEFFE3C489F24F695B6411DB7E22CCC85A8594");

    private static final SecureRandom RANDOM = new SecureRandom();
    private static ECParameterSpec params;
    /** Solo para la autoprueba: permite simular el equipo con otra clave. */
    private static PublicKey peerSigningKeyOverride;

    static void setPeerSigningKeyForTest(PublicKey publicKey) {
        peerSigningKeyOverride = publicKey;
    }

    private byte[] unsecureKey;
    private byte[] unsecureIv;
    private byte[] secureKey;
    private byte[] peerPubRaw;
    private PrivateKey myPrivate;
    private PublicKey myPublic;

    // ------------------------------------------------------------ parámetros

    public static synchronized ECParameterSpec params() {
        if (params == null) {
            try {
                AlgorithmParameters algorithmParameters = AlgorithmParameters.getInstance("EC");
                algorithmParameters.init(new ECGenParameterSpec("secp256r1"));
                params = algorithmParameters.getParameterSpec(ECParameterSpec.class);
            } catch (Exception exc) {
                throw new IllegalStateException("secp256r1 no disponible", exc);
            }
        }
        return params;
    }

    public static PublicKey k2PublicKey() throws Exception {
        if (peerSigningKeyOverride != null) {
            return peerSigningKeyOverride;
        }
        return KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(PUBLIC_KEY_K2));
    }

    public static PrivateKey l1PrivateKey() throws Exception {
        BigInteger scalar = new BigInteger(1, PRIVATE_KEY_L1);
        return KeyFactory.getInstance("EC").generatePrivate(new ECPrivateKeySpec(scalar, params()));
    }

    public static PrivateKey privateKeyFromScalar(byte[] scalar32) throws Exception {
        return KeyFactory.getInstance("EC").generatePrivate(
                new ECPrivateKeySpec(new BigInteger(1, Hex.padLeft(scalar32, 32)), params()));
    }

    public static PublicKey publicKeyFromRaw(byte[] raw64) throws Exception {
        if (raw64 == null || raw64.length != 64) {
            throw new IllegalArgumentException("clave pública de 64 bytes esperada");
        }
        BigInteger x = new BigInteger(1, Arrays.copyOfRange(raw64, 0, 32));
        BigInteger y = new BigInteger(1, Arrays.copyOfRange(raw64, 32, 64));
        return KeyFactory.getInstance("EC").generatePublic(
                new ECPublicKeySpec(new ECPoint(x, y), params()));
    }

    public static byte[] publicKeyToRaw(PublicKey publicKey) {
        ECPoint point = ((java.security.interfaces.ECPublicKey) publicKey).getW();
        byte[] x = Hex.padLeft(point.getAffineX().toByteArray(), 32);
        byte[] y = Hex.padLeft(point.getAffineY().toByteArray(), 32);
        return Hex.concat(x, y);
    }

    public static byte[] ecdh(PrivateKey privateKey, PublicKey publicKey) throws Exception {
        KeyAgreement agreement = KeyAgreement.getInstance("ECDH");
        agreement.init(privateKey);
        agreement.doPhase(publicKey, true);
        return Hex.padLeft(agreement.generateSecret(), 32);
    }

    public static byte[] signSha256(PrivateKey privateKey, byte[] data) throws Exception {
        Signature signature = Signature.getInstance("SHA256withECDSA");
        signature.initSign(privateKey);
        signature.update(data);
        return signature.sign();
    }

    public static boolean verifySha256(PublicKey publicKey, byte[] data, byte[] derSignature)
            throws Exception {
        Signature signature = Signature.getInstance("SHA256withECDSA");
        signature.initVerify(publicKey);
        signature.update(data);
        return signature.verify(derSignature);
    }

    // ---------------------------------------------------- firmas raw <-> DER

    private static byte[] derInteger(byte[] value) {
        int start = 0;
        while (start < value.length - 1 && value[start] == 0) {
            start++;
        }
        byte[] trimmed = Arrays.copyOfRange(value, start, value.length);
        boolean negative = (trimmed[0] & 0x80) != 0;
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(0x02);
        out.write(trimmed.length + (negative ? 1 : 0));
        if (negative) {
            out.write(0x00);
        }
        out.write(trimmed, 0, trimmed.length);
        return out.toByteArray();
    }

    public static byte[] rawToDerSignature(byte[] rawSignature) {
        if (rawSignature.length != 64) {
            throw new IllegalArgumentException("firma raw de 64 bytes esperada");
        }
        byte[] r = derInteger(Arrays.copyOfRange(rawSignature, 0, 32));
        byte[] s = derInteger(Arrays.copyOfRange(rawSignature, 32, 64));
        byte[] body = Hex.concat(r, s);
        return Hex.concat(new byte[] {0x30, (byte) body.length}, body);
    }

    public static byte[] derToRawSignature(byte[] derSignature) {
        int index = 0;
        if ((derSignature[index++] & 0xFF) != 0x30) {
            throw new IllegalArgumentException("DER: falta SEQUENCE");
        }
        int length = derSignature[index++] & 0xFF;
        if (length == 0x81) {
            length = derSignature[index++] & 0xFF;
        } else if (length == 0x82) {
            length = ((derSignature[index] & 0xFF) << 8) | (derSignature[index + 1] & 0xFF);
            index += 2;
        }
        if ((derSignature[index++] & 0xFF) != 0x02) {
            throw new IllegalArgumentException("DER: falta INTEGER r");
        }
        int rLength = derSignature[index++] & 0xFF;
        byte[] r = Arrays.copyOfRange(derSignature, index, index + rLength);
        index += rLength;
        if ((derSignature[index++] & 0xFF) != 0x02) {
            throw new IllegalArgumentException("DER: falta INTEGER s");
        }
        int sLength = derSignature[index++] & 0xFF;
        byte[] s = Arrays.copyOfRange(derSignature, index, index + sLength);
        byte[] raw = new byte[64];
        byte[] rPadded = Hex.padLeft(new BigInteger(1, r).toByteArray(), 32);
        byte[] sPadded = Hex.padLeft(new BigInteger(1, s).toByteArray(), 32);
        System.arraycopy(rPadded, 0, raw, 0, 32);
        System.arraycopy(sPadded, 0, raw, 32, 32);
        return raw;
    }

    // ------------------------------------------------------------- AES-CBC

    private static byte[] lengthBytes(int length) {
        return new byte[] {(byte) ((length >> 8) & 0xFF), (byte) (length & 0xFF)};
    }

    public static byte[] aesEncrypt(byte[] plain, byte[] key, byte[] fixedIvOrNull) throws Exception {
        byte[] header;
        byte[] iv;
        if (fixedIvOrNull == null) {
            byte[] seed = new byte[4];
            RANDOM.nextBytes(seed);
            header = Hex.concat(lengthBytes(plain.length), seed);
            iv = Hex.md5(seed);
        } else {
            header = lengthBytes(plain.length);
            iv = fixedIvOrNull;
        }
        int paddedLength = ((plain.length + 15) / 16) * 16;
        byte[] padded = new byte[paddedLength];
        System.arraycopy(plain, 0, padded, 0, plain.length);
        Cipher cipher = Cipher.getInstance("AES/CBC/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new IvParameterSpec(iv));
        byte[] encrypted = cipher.doFinal(padded);
        return Hex.concat(header, encrypted);
    }

    public static byte[] aesDecrypt(byte[] block, byte[] key, byte[] fixedIvOrNull) throws Exception {
        int dataLength = ((block[0] & 0xFF) << 8) | (block[1] & 0xFF);
        byte[] iv;
        int offset;
        if (fixedIvOrNull == null) {
            byte[] seed = Arrays.copyOfRange(block, 2, 6);
            iv = Hex.md5(seed);
            offset = 6;
        } else {
            iv = fixedIvOrNull;
            offset = 2;
        }
        Cipher cipher = Cipher.getInstance("AES/CBC/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new IvParameterSpec(iv));
        byte[] decrypted = cipher.doFinal(Arrays.copyOfRange(block, offset, block.length));
        if (dataLength > decrypted.length) {
            throw new IllegalStateException("longitud descifrada incoherente");
        }
        return Arrays.copyOf(decrypted, dataLength);
    }

    /** Longitud total del bloque cifrado según el prefijo de longitud del buffer. */
    public int expectedEncryptedLength(byte[] buffer) {
        if (buffer.length < 2) {
            return -1;
        }
        int dataLength = ((buffer[0] & 0xFF) << 8) | (buffer[1] & 0xFF);
        int header = secureKey == null ? 2 : 6;
        int padded = ((dataLength + 15) / 16) * 16;
        return header + padded;
    }

    // ------------------------------------------------------------ handshake

    public static boolean isPreKey(byte[] message) {
        return message != null && message.length >= 6
                && (message[0] & 0xFF) == 0x2A && (message[1] & 0xFF) == 0x2A;
    }

    public int typeOf(byte[] message) {
        return message[2] & 0xFF;
    }

    /**
     * Procesa un mensaje crudo del equipo (sin cifrar) antes del intercambio.
     *
     * @return bytes a escribir de vuelta, o null si no hay respuesta.
     */
    public byte[] onRawMessage(byte[] message) throws Exception {
        if (!isPreKey(message)) {
            return null;
        }
        int type = typeOf(message);
        byte[] data = Arrays.copyOfRange(message, 4, message.length - 2);
        switch (type) {
            case TYPE_CHALLENGE:
                if (data.length != 4) {
                    throw new IllegalStateException("challenge con longitud inesperada");
                }
                unsecureIv = Hex.md5(Hex.reversed(data));
                unsecureKey = Hex.xor(unsecureIv, LOCAL_AES_KEY);
                byte[] replyBody = Hex.concat(new byte[] {0x02, 0x04},
                        Arrays.copyOfRange(unsecureIv, 8, 12));
                return Hex.concat(MAGIC, replyBody, Hex.checksum(replyBody));
            case TYPE_CHALLENGE_ACCEPTED:
                return null;
            case TYPE_PEER_PUBKEY:
                return handlePeerPublicKey(data);
            default:
                return null;
        }
    }

    private byte[] handlePeerPublicKey(byte[] data) throws Exception {
        if (data.length != 128) {
            throw new IllegalStateException("peer pubkey con longitud inesperada: " + data.length);
        }
        if (unsecureKey == null || unsecureIv == null) {
            throw new IllegalStateException("llegó la clave del equipo antes del challenge");
        }
        byte[] peerRaw = Arrays.copyOfRange(data, 0, 64);
        byte[] signatureRaw = Arrays.copyOfRange(data, 64, 128);
        byte[] signedData = Hex.concat(peerRaw, unsecureIv);
        boolean valid = verifySha256(k2PublicKey(), signedData, rawToDerSignature(signatureRaw));
        if (!valid) {
            throw new IllegalStateException("firma del equipo inválida");
        }
        peerPubRaw = peerRaw;

        KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
        generator.initialize(new ECGenParameterSpec("secp256r1"), RANDOM);
        KeyPair pair = generator.generateKeyPair();
        myPrivate = pair.getPrivate();
        myPublic = pair.getPublic();
        byte[] myRaw = publicKeyToRaw(myPublic);

        byte[] derSignature = signSha256(l1PrivateKey(), Hex.concat(myRaw, unsecureIv));
        byte[] rawSignature = derToRawSignature(derSignature);
        byte[] body = Hex.concat(new byte[] {0x05, (byte) 0x80}, myRaw, rawSignature);
        byte[] message = Hex.concat(MAGIC, body, Hex.checksum(body));
        return aesEncrypt(message, unsecureKey, unsecureIv);
    }

    /**
     * Procesa un mensaje KEX ya descifrado (la clave pública del equipo llega
     * cifrada con la clave temporal) y devuelve la respuesta cifrada a escribir.
     */
    public byte[] peerPubkeyReply(byte[] message) throws Exception {
        if (!isPreKey(message)) {
            throw new IllegalStateException("no es un mensaje pre-key");
        }
        byte[] data = Arrays.copyOfRange(message, 4, message.length - 2);
        return handlePeerPublicKey(data);
    }

    /**
     * Procesa un bloque ya descifrado.
     *
     * @return carga MODBUS, o null si era parte del handshake.
     */
    public byte[] onDecryptedMessage(byte[] plain) throws Exception {
        if (!isPreKey(plain)) {
            return plain;
        }
        int type = typeOf(plain);
        if (type == TYPE_PUBKEY_ACCEPTED) {
            byte[] data = Arrays.copyOfRange(plain, 4, plain.length - 2);
            if (data.length != 1 || data[0] != 0) {
                throw new IllegalStateException("confirmación de clave inesperada");
            }
            if (myPrivate == null || peerPubRaw == null) {
                throw new IllegalStateException("confirmación de clave antes del intercambio");
            }
            secureKey = ecdh(myPrivate, publicKeyFromRaw(peerPubRaw));
        }
        return null;
    }

    public byte[] decryptTransport(byte[] block) throws Exception {
        if (secureKey == null) {
            return aesDecrypt(block, unsecureKey, unsecureIv);
        }
        return aesDecrypt(block, secureKey, null);
    }

    public byte[] encryptTransport(byte[] plain) throws Exception {
        if (secureKey == null) {
            throw new IllegalStateException("canal cifrado no preparado");
        }
        return aesEncrypt(plain, secureKey, null);
    }

    public boolean isReady() {
        return secureKey != null && peerPubRaw != null;
    }

    public boolean isEncrypted() {
        return secureKey != null;
    }

    public byte[] secureKey() {
        return secureKey;
    }

    public byte[] unsecureIv() {
        return unsecureIv;
    }
}
