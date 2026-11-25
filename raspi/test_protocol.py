"""Autopruebas del protocolo para el port de Raspberry Pi (sin BLE).

Ejecutar:  python -m unittest raspi.test_protocol -v
"""

from __future__ import annotations

import hashlib
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from raspi import bluetti_protocol as bp


class ModbusTest(unittest.TestCase):
    def test_crc_and_requests(self):
        self.assertEqual(bp.crc16(bytes.fromhex("010300660001")), 0x1564)
        self.assertEqual(bp.modbus_read_request(102, 1).hex(), "0103006600016415")
        self.assertEqual(bp.modbus_read_request(110, 6).hex(), "0103006e0006a415")
        self.assertEqual(bp.modbus_read_request(140, 1).hex(), "0103008c000145e1")

    def test_response(self):
        body = bp.parse_read_response(bytes.fromhex("010302005a387f"), 1)
        self.assertIsNotNone(body)
        self.assertEqual(bp.u16(body), 90)
        self.assertIsNone(bp.parse_read_response(bytes.fromhex("010302005a387e"), 1))

    def test_swap_string(self):
        self.assertEqual(bp.swap_string(bytes.fromhex("434138315030")), "AC180P")

    def test_names(self):
        self.assertTrue(bp.is_bluetti_name("AC180P2507003893321"))
        self.assertFalse(bp.is_bluetti_name("TV Samsung"))
        self.assertTrue(bp.is_valid_device_type("AC180P"))


class CryptoTest(unittest.TestCase):
    def test_challenge_vectors(self):
        crypto = bp.Crypto()
        body = bytes.fromhex("0104") + bytes.fromhex("a1b2c3d4")
        message = bp.KEX_MAGIC + body + bp._checksum(body)
        reply = crypto.msg_challenge(message)
        self.assertEqual(reply.hex(), bp.KEX_MAGIC.hex() + "020405a25513" + "0115")
        self.assertEqual(crypto.unsecure_iv.hex(), "56b80d4da723052405a25513d238e70a")
        self.assertEqual(crypto.unsecure_key.hex(), "1327c87827aa44d57533b58aecdb0e37")

    def test_aes_vectors(self):
        key = bytes(range(32))
        iv = hashlib.md5(bytes.fromhex("01020304")).digest()
        plain = bytes.fromhex("0103006600016415")
        encrypted = bp.Crypto.aes_encrypt_static(plain, key, iv)
        self.assertEqual(
            encrypted.hex(), "0008ed3ed23afd450394a46e2f03bb6bcdd5"
        )
        self.assertEqual(
            bp.Crypto.aes_decrypt_static(encrypted, key, iv).hex(), plain.hex()
        )
        seeded = bytes.fromhex("000801020304ed3ed23afd450394a46e2f03bb6bcdd5")
        self.assertEqual(
            bp.Crypto.aes_decrypt_static(seeded, key, None).hex(), plain.hex()
        )

    def test_ecdh_vector(self):
        shared = bp.Crypto.ecdh_static(
            ec.derive_private_key(
                int("11" * 32, 16), ec.SECP256R1()
            ),
            ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(),
                b"\x04"
                + bytes.fromhex(
                    "d65a93977caa3d1b081852ff57a79e465f1660577304baead505dd3a48589cf3"
                    "50185e895372df6221ea3a137557e473fddb6755f05bd507c3c533fce9c91285"
                ),
            ),
        )
        self.assertEqual(
            shared.hex(),
            "ccfc261f58193c98ca4ad4a53bbac6f0ee29bc4d48438090446908622ca79af6",
        )

    def test_signature_roundtrip(self):
        data = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        device_key = ec.generate_private_key(ec.SECP256R1())
        der = device_key.sign(data, ec.ECDSA(hashes.SHA256()))
        raw = bp.Crypto.der_to_raw(der)
        self.assertEqual(len(raw), 64)
        self.assertEqual(bp.Crypto.raw_to_der(raw), der)
        device_key.public_key().verify(
            bp.Crypto.raw_to_der(raw), data, ec.ECDSA(hashes.SHA256())
        )


class HandshakeTest(unittest.TestCase):
    """Simula el equipo (challenge + peer pubkey + PUBKEY_ACCEPTED)."""

    def test_full_handshake(self):
        device_key = ec.generate_private_key(ec.SECP256R1())
        device_raw = device_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )[1:]
        crypto = bp.Crypto(peer_signing_public=device_key.public_key())

        # 1. challenge
        challenge_body = bytes.fromhex("0104") + bytes.fromhex("a1b2c3d4")
        challenge = bp.KEX_MAGIC + challenge_body + bp._checksum(challenge_body)
        reply = crypto.msg_challenge(challenge)
        self.assertEqual(reply.hex(), "2a2a020405a255130115")
        self.assertEqual(crypto.unsecure_iv.hex(), "56b80d4da723052405a25513d238e70a")

        # 2. CHALLENGE_ACCEPTED (sin respuesta)

        # 3. peer pubkey: el equipo la envía cifrada con la clave temporal
        der_signature = device_key.sign(
            device_raw + crypto.unsecure_iv, ec.ECDSA(hashes.SHA256())
        )
        raw_signature = crypto.der_to_raw(der_signature)
        peer_body = bytes([bp.TYPE_PEER_PUBKEY, 0x80]) + device_raw + raw_signature
        peer_message = bp.KEX_MAGIC + peer_body + bp._checksum(peer_body)
        peer_encrypted = crypto.aes_encrypt(
            peer_message, crypto.unsecure_key, crypto.unsecure_iv
        )
        peer_plain = crypto.decrypt_transport(peer_encrypted)
        encrypted_reply = crypto.msg_peer_pubkey(peer_plain)
        self.assertIsNotNone(encrypted_reply)
        reply_plain = crypto.aes_decrypt(
            encrypted_reply, crypto.unsecure_key, crypto.unsecure_iv
        )
        self.assertTrue(bp.is_pre_key(reply_plain))
        self.assertEqual(reply_plain[2], 0x05)
        client_raw = reply_plain[4:68]
        self.assertEqual(len(client_raw), 64)

        expected_secure = device_key.exchange(
            ec.ECDH(),
            ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(), b"\x04" + client_raw
            ),
        )

        # 4. PUBKEY_ACCEPTED cifrado con la clave temporal
        accepted_body = bytes([bp.TYPE_PUBKEY_ACCEPTED, 0x01, 0x00])
        accepted_message = bp.KEX_MAGIC + accepted_body + bp._checksum(accepted_body)
        encrypted = crypto.aes_encrypt(
            accepted_message, crypto.unsecure_key, crypto.unsecure_iv
        )
        self.assertEqual(crypto.expected_length(encrypted), len(encrypted))
        plain = crypto.decrypt_transport(encrypted)
        crypto.msg_key_accepted(plain)
        self.assertTrue(crypto.ready)
        self.assertEqual(crypto.secure_key, expected_secure)

        # 5. transporte cifrado de una petición MODBUS
        request = bp.modbus_read_request(102, 1)
        wire = crypto.encrypt_transport(request)
        self.assertEqual(crypto.expected_length(wire), len(wire))
        self.assertEqual(crypto.decrypt_transport(wire), request)


if __name__ == "__main__":
    unittest.main()
