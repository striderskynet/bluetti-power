package com.striderskynet.bluetti;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.spec.ECGenParameterSpec;
import java.util.Arrays;

/**
 * Autoprueba del protocolo (sin Android): MODBUS, criptografía y handshake
 * cifrado completo simulado. Se ejecuta en el build.
 *
 * <p>Los vectores marcados como "python" se generaron con la implementación de
 * referencia (bluetti-bt-lib) para validar el port a Java.</p>
 */
public final class ProtocolSelfTest {

    private static int failures;

    public static void main(String[] args) throws Exception {
        testChecksum();
        testModbus();
        testChallengeReply();
        testAes();
        testEcdh();
        testSignature();
        testFullHandshake();
        if (failures > 0) {
            System.out.println("FALLOS: " + failures);
            System.exit(1);
        }
        System.out.println("ProtocolSelfTest OK");
    }

    // ---------------------------------------------------------------- tests

    private static void testChecksum() {
        byte[] body = Hex.fromHex("0204aabbccdd");
        checkHex("checksum", Hex.checksum(body), "0314");
    }

    private static void testModbus() {
        checkHex("read 102", Modbus.readRequest(102, 1), "0103006600016415");
        checkHex("read 110", Modbus.readRequest(110, 6), "0103006e0006a415");
        checkHex("read 140", Modbus.readRequest(140, 1), "0103008c000145e1");
        check("crc", Modbus.crc16(Hex.fromHex("010300660001"), 6) == 0x1564);

        byte[] response = Hex.fromHex("010302005a387f");
        byte[] body = Modbus.parseReadResponse(response, 1);
        check("parse response", body != null && Modbus.u16(body, 0) == 90);

        byte[] bad = Hex.fromHex("010302005a387e");
        check("parse crc inválido", Modbus.parseReadResponse(bad, 1) == null);

        check("swapString", "AC180P".equals(Modbus.swapString(Hex.fromHex("434138315030"))));
    }

    private static void testChallengeReply() throws Exception {
        BluettiCrypto client = new BluettiCrypto();
        byte[] body = Hex.concat(new byte[] {0x01, 0x04}, Hex.fromHex("a1b2c3d4"));
        byte[] message = Hex.concat(BluettiCrypto.MAGIC, body, Hex.checksum(body));
        byte[] reply = client.onRawMessage(message);
        checkHex("challenge reply (python)", reply, "2a2a020405a255130115");
        checkHex("unsecure iv (python)", client.unsecureIv(), "56b80d4da723052405a25513d238e70a");
        checkHex("unsecure key (python)",
                Hex.xor(client.unsecureIv(), BluettiCrypto.LOCAL_AES_KEY),
                "1327c87827aa44d57533b58aecdb0e37");
    }

    private static void testAes() throws Exception {
        byte[] key = new byte[32];
        for (int i = 0; i < 32; i++) {
            key[i] = (byte) i;
        }
        byte[] iv = Hex.md5(Hex.fromHex("01020304"));
        byte[] plain = Hex.fromHex("0103006600016415");

        byte[] encrypted = BluettiCrypto.aesEncrypt(plain, key, iv);
        checkHex("aes cifrado (python)", encrypted, "0008ed3ed23afd450394a46e2f03bb6bcdd5");
        checkHex("aes descifrado", BluettiCrypto.aesDecrypt(encrypted, key, iv), "0103006600016415");

        byte[] seeded = Hex.fromHex("000801020304ed3ed23afd450394a46e2f03bb6bcdd5");
        byte[] decrypted = BluettiCrypto.aesDecrypt(seeded, key, null);
        checkHex("aes viejo descifrado", decrypted, "0103006600016415");
    }

    private static void testEcdh() throws Exception {
        byte[] shared = BluettiCrypto.ecdh(
                BluettiCrypto.privateKeyFromScalar(Hex.fromHex(
                        "1111111111111111111111111111111111111111111111111111111111111111")),
                BluettiCrypto.publicKeyFromRaw(Hex.fromHex(
                        "d65a93977caa3d1b081852ff57a79e465f1660577304baead505dd3a48589cf3"
                                + "50185e895372df6221ea3a137557e473fddb6755f05bd507c3c533fce9c91285")));
        checkHex("ecdh (python)", shared,
                "ccfc261f58193c98ca4ad4a53bbac6f0ee29bc4d48438090446908622ca79af6");
    }

    private static void testSignature() throws Exception {
        byte[] data = Hex.fromHex("000102030405060708090a0b0c0d0e0f");
        byte[] der = Hex.fromHex(
                "3045022100917c15a333be4c759cb701b17972bfb18f7232bf8dc7e3fb9b193956b945221f"
                        + "02200a114bfc02dc3d2754e0f029417264b5d2b4df2b8e14f9cb5e4450beafda382f");
        byte[] raw = Hex.fromHex(
                "917c15a333be4c759cb701b17972bfb18f7232bf8dc7e3fb9b193956b945221f"
                        + "0a114bfc02dc3d2754e0f029417264b5d2b4df2b8e14f9cb5e4450beafda382f");

        checkHex("raw -> DER", BluettiCrypto.rawToDerSignature(raw), Hex.toHex(der));
        checkHex("DER -> raw", BluettiCrypto.derToRawSignature(der), Hex.toHex(raw));

        // La firma del vector es de L1 (lado cliente); el equipo firma con otra clave.
        // Comprobamos que el proveedor EC de la plataforma firma y verifica bien.
        KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
        generator.initialize(new ECGenParameterSpec("secp256r1"));
        KeyPair pair = generator.generateKeyPair();
        byte[] signature = BluettiCrypto.signSha256(pair.getPrivate(), data);
        check("firma EC propia", BluettiCrypto.verifySha256(pair.getPublic(), data, signature));
        check("firma EC alterada", !BluettiCrypto.verifySha256(pair.getPublic(),
                Hex.fromHex("000102030405060708090a0b0c0d0e0e"), signature));

        check("carga clave K2", BluettiCrypto.k2PublicKey() != null);
        check("carga clave L1", BluettiCrypto.l1PrivateKey() != null);
    }

    /** Simula el equipo: challenge, peer pubkey firmada y PUBKEY_ACCEPTED. */
    private static void testFullHandshake() throws Exception {
        BluettiCrypto client = new BluettiCrypto();

        KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
        generator.initialize(new ECGenParameterSpec("secp256r1"));
        KeyPair devicePair = generator.generateKeyPair();
        byte[] devicePubRaw = BluettiCrypto.publicKeyToRaw(devicePair.getPublic());
        // El equipo real firma con la clave privada de K2 (no la tenemos), así que
        // en la simulación usamos un par propio como "clave del fabricante".
        BluettiCrypto.setPeerSigningKeyForTest(devicePair.getPublic());
        try {
            runHandshakeSimulation(client, devicePair, devicePubRaw);
        } finally {
            BluettiCrypto.setPeerSigningKeyForTest(null);
        }
    }

    private static void runHandshakeSimulation(BluettiCrypto client, KeyPair devicePair,
                                               byte[] devicePubRaw) throws Exception {
        // 1. challenge del equipo
        byte[] challengeBody = Hex.concat(new byte[] {0x01, 0x04}, Hex.fromHex("a1b2c3d4"));
        byte[] challenge = Hex.concat(BluettiCrypto.MAGIC, challengeBody, Hex.checksum(challengeBody));
        byte[] challengeReply = client.onRawMessage(challenge);
        checkHex("handshake: challenge", challengeReply, "2a2a020405a255130115");
        byte[] unsecureKey = Hex.xor(client.unsecureIv(), BluettiCrypto.LOCAL_AES_KEY);

        // 2. CHALLENGE_ACCEPTED
        byte[] acceptedBody = new byte[] {0x03, 0x00};
        check("handshake: accepted", client.onRawMessage(
                Hex.concat(BluettiCrypto.MAGIC, acceptedBody, Hex.checksum(acceptedBody))) == null);

        // 3. peer pubkey: el equipo real la envía cifrada con la clave temporal
        byte[] derSignature = BluettiCrypto.signSha256(devicePair.getPrivate(),
                Hex.concat(devicePubRaw, client.unsecureIv()));
        byte[] rawSignature = BluettiCrypto.derToRawSignature(derSignature);
        byte[] peerBody = Hex.concat(new byte[] {0x04, (byte) 0x80},
                devicePubRaw, rawSignature);
        byte[] peerMessage = Hex.concat(BluettiCrypto.MAGIC, peerBody, Hex.checksum(peerBody));
        byte[] peerEncrypted = BluettiCrypto.aesEncrypt(
                peerMessage, unsecureKey, client.unsecureIv());
        byte[] peerPlain = client.decryptTransport(peerEncrypted);

        byte[] reply = client.peerPubkeyReply(peerPlain);
        check("handshake: respuesta al peer pubkey", reply != null);
        byte[] replyPlain = BluettiCrypto.aesDecrypt(reply, unsecureKey, client.unsecureIv());
        check("handshake: respuesta 2a2a", BluettiCrypto.isPreKey(replyPlain));
        check("handshake: tipo respuesta (5)", (replyPlain[2] & 0xFF) == 5);
        check("handshake: longitud respuesta", replyPlain.length == 134);

        byte[] clientPubRaw = Arrays.copyOfRange(replyPlain, 4, 68);
        byte[] clientSignature = Arrays.copyOfRange(replyPlain, 68, 132);
        check("handshake: longitud de la firma del cliente", clientSignature.length == 64);

        byte[] expectedSecure = BluettiCrypto.ecdh(devicePair.getPrivate(),
                BluettiCrypto.publicKeyFromRaw(clientPubRaw));

        // 4. PUBKEY_ACCEPTED (cifrado con la clave temporal)
        byte[] keyAcceptedBody = new byte[] {0x06, 0x01, 0x00};
        byte[] keyAcceptedMessage = Hex.concat(
                BluettiCrypto.MAGIC, keyAcceptedBody, Hex.checksum(keyAcceptedBody));
        byte[] encrypted = BluettiCrypto.aesEncrypt(keyAcceptedMessage, unsecureKey,
                client.unsecureIv());
        check("handshake: longitud cifrada", client.expectedEncryptedLength(encrypted) == encrypted.length);
        byte[] plain = client.decryptTransport(encrypted);
        check("handshake: mensaje aceptado", client.onDecryptedMessage(plain) == null);
        check("handshake: canal listo", client.isReady());
        checkHex("handshake: clave segura", client.secureKey(), Hex.toHex(expectedSecure));

        // 5. una petición MODBUS cifrada se descifra correctamente
        byte[] request = Modbus.readRequest(102, 1);
        byte[] wire = client.encryptTransport(request);
        check("transporte: longitud", client.expectedEncryptedLength(wire) == wire.length);
        checkHex("transporte: ida y vuelta",
                BluettiCrypto.aesDecrypt(wire, expectedSecure, null), "0103006600016415");
    }

    // ------------------------------------------------------------- helpers

    private static void check(String name, boolean condition) {
        if (condition) {
            System.out.println("  OK   " + name);
        } else {
            failures++;
            System.out.println("  FAIL " + name);
        }
    }

    private static void checkHex(String name, byte[] actual, String expected) {
        String actualHex = Hex.toHex(actual);
        if (actualHex.equalsIgnoreCase(expected)) {
            System.out.println("  OK   " + name);
        } else {
            failures++;
            System.out.println("  FAIL " + name + "\n       esperado: " + expected + "\n       obtenido: " + actualHex);
        }
    }
}
