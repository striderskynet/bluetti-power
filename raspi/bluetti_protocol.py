"""Protocolo BLE/MODBUS del BLUETTI AC180P para Linux (arm64, headless).

Implementación autocontenida: solo necesita ``bleak`` y ``cryptography``
(ambos con wheels precompilados para aarch64). No usa ``bluetti-bt-lib`` para
evitar dependencias que requieran compilador (crcmod) en Raspberry Pi OS Lite.

El handshake cifrado es un port de ``bluetti-bt-lib/bluetooth/encryption.py``
(Patrick762, MIT), basado en el trabajo de nhurman/warhammerkid, validado
contra un AC180P real. La lógica se comparte con la versión Java de Android.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

LOGGER = logging.getLogger("bluetti.protocol")

NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

KEX_MAGIC = b"**"
LOCAL_AES_KEY = bytes.fromhex("459FC535808941F17091E0993EE3E93D")
PRIVATE_KEY_L1 = bytes.fromhex(
    "4F19A16E3E87BDD9BD24D3E5495B88041511943CBC8B969ADE9641D0F56AF337"
)
PUBLIC_KEY_K2_DER = bytes.fromhex(
    "3059301306072a8648ce3d020106082a8648ce3d03010703420004"
    "A73ABF5D2232C8C1C72E68304343C272495E3A8FD6F30EA96DE2F4B3CE60B251"
    "EE21AC667CF8A71E18B46B664EAEFFE3C489F24F695B6411DB7E22CCC85A8594"
)

TYPE_CHALLENGE = 1
TYPE_CHALLENGE_ACCEPTED = 3
TYPE_PEER_PUBKEY = 4
TYPE_PUBKEY_ACCEPTED = 6

#: Registros del AC180P (misma tabla que Windows/Android).
READ_REGISTERS: tuple[tuple[int, int], ...] = (
    (102, 1),   # SOC
    (110, 6),   # modelo
    (140, 1),   # salida DC
    (142, 1),   # salida AC
    (144, 1),   # entrada DC (solar)
    (146, 1),   # entrada AC (red)
)

MODEL_PREFIXES = (
    "AC2A", "AC50", "AC60", "AC70", "AC180", "AC200", "AC300", "AC500",
    "AP300", "EB3A", "EB70", "EL10", "EL30", "EL100", "EP500", "EP600",
    "EP760", "EP800", "EP2000", "Handsfree", "PR30", "PR100", "PBOX",
    "BLUETTI",
)

SCAN_TIMEOUT = 6.0
READ_TIMEOUT = 50.0
WRITE_TIMEOUT = 8.0


class BluettiError(RuntimeError):
    """Error de comunicación con el equipo."""


# --------------------------------------------------------------------- CRC/MODBUS


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS (polinomio 0xA001, inicial 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte & 0xFF
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def modbus_read_request(address: int, quantity: int) -> bytes:
    cmd = struct.pack("!BBHH", 0x01, 0x03, address, quantity)
    return cmd + struct.pack("<H", crc16(cmd))


def parse_read_response(response: bytes, quantity: int) -> bytes | None:
    if len(response) < 5 or response[0] != 0x01 or response[1] != 0x03:
        return None
    if response[2] != quantity * 2 or len(response) != quantity * 2 + 5:
        return None
    received = response[-2] | (response[-1] << 8)
    if crc16(response[:-2]) != received:
        return None
    return response[3:-2]


def u16(body: bytes, index: int = 0) -> int:
    return (body[index] << 8) | body[index + 1]


def swap_string(data: bytes) -> str:
    out = bytearray(data)
    for i in range(0, len(out) - 1, 2):
        out[i], out[i + 1] = out[i + 1], out[i]
    return bytes(out).rstrip(b"\x00").decode("ascii", errors="ignore").strip()


def is_bluetti_name(name: str) -> bool:
    upper = (name or "").upper()
    return any(upper.startswith(prefix.upper()) for prefix in MODEL_PREFIXES)


def is_valid_device_type(device_type: str) -> bool:
    return bool(device_type) and len(device_type) >= 3 and is_bluetti_name(device_type)


# --------------------------------------------------------------- anuncio BLE


def encryption_hint(manufacturer_data: dict[int, bytes] | None) -> bool | None:
    """Deduce del anuncio si el canal viene cifrado (BLUETTI vs BLUETTF)."""
    if not manufacturer_data:
        return None
    plain = False
    for payload in manufacturer_data.values():
        try:
            raw = bytes(payload)
        except TypeError:
            continue
        if b"BLUETTF" in raw:
            return True
        if b"BLUETTI" in raw:
            plain = True
    return False if plain else None


@dataclass
class ScanHit:
    address: str
    name: str
    rssi: int | None = None
    encrypted: bool | None = None

    def label(self) -> str:
        flag = "" if self.encrypted is None else (" · cifrado" if self.encrypted else " · sin cifrar")
        rssi = f"{self.rssi} dBm" if self.rssi is not None else "?"
        return f"{self.address}  {rssi:>9}  {self.name}{flag}"


async def scan(timeout: float = 8.0) -> list[ScanHit]:
    """Escanea equipos BLUETTI visibles, ordenados por señal."""
    try:
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except Exception as exc:  # noqa: BLE001 - se informa al usuario
        raise BluettiError(f"no se pudo escanear Bluetooth: {exc}") from exc

    hits: list[ScanHit] = []
    for address, (device, advertisement) in discovered.items():
        name = (device.name or advertisement.local_name or "").strip()
        if not name or not is_bluetti_name(name):
            continue
        hits.append(
            ScanHit(
                address=address,
                name=name,
                rssi=getattr(advertisement, "rssi", None),
                encrypted=encryption_hint(getattr(advertisement, "manufacturer_data", None)),
            )
        )
    hits.sort(key=lambda hit: (hit.rssi if hit.rssi is not None else -999), reverse=True)
    return hits


async def scan_for(name: str, timeout: float = 6.0) -> ScanHit | None:
    hits = await scan(timeout=timeout)
    prefix = (name or "").strip()[:5].upper()
    for hit in hits:
        if not prefix or hit.name.upper().startswith(prefix):
            return hit
    return hits[0] if hits else None


# ------------------------------------------------------------------- cifrado


class Crypto:
    """Handshake y cifrado del canal BLE (lado cliente)."""

    def __init__(self, peer_signing_public=None) -> None:
        self.unsecure_key: bytes | None = None
        self.unsecure_iv: bytes | None = None
        self.secure_key: bytes | None = None
        self.peer_pub_raw: bytes | None = None
        self.my_private = None
        self.my_public = None
        self._peer_signing_public = peer_signing_public or serialization.load_der_public_key(
            PUBLIC_KEY_K2_DER
        )

    # -- estado ---------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self.secure_key is not None and self.peer_pub_raw is not None

    def get_key_iv(self):
        if self.secure_key is not None:
            return self.secure_key, None
        return self.unsecure_key, self.unsecure_iv

    def expected_length(self, buffer: bytes | bytearray) -> int:
        """Longitud total del bloque cifrado según su prefijo, o -1 si faltan datos."""
        if len(buffer) < 2:
            return -1
        data_length = (buffer[0] << 8) | buffer[1]
        header = 6 if self.secure_key is not None else 2
        padded = ((data_length + 15) // 16) * 16
        return header + padded

    # -- AES ------------------------------------------------------------
    def aes_encrypt(self, data: bytes, key: bytes, iv: bytes | None = None) -> bytes:
        return self.aes_encrypt_static(data, key, iv)

    def aes_decrypt(self, data: bytes, key: bytes, iv: bytes | None = None) -> bytes:
        return self.aes_decrypt_static(data, key, iv)

    @staticmethod
    def aes_encrypt_static(data: bytes, key: bytes, iv: bytes | None = None) -> bytes:
        header = len(data).to_bytes(2, "big")
        if iv is None:
            seed = os.urandom(4)
            header += seed
            iv = hashlib.md5(seed).digest()
        padding = (-len(data)) % 16
        padded = data + b"\x00" * padding
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        return header + ciphertext

    @staticmethod
    def aes_decrypt_static(data: bytes, key: bytes, iv: bytes | None = None) -> bytes:
        length = (data[0] << 8) | data[1]
        if iv is None:
            iv = hashlib.md5(data[2:6]).digest()
            ciphertext = data[6:]
        else:
            ciphertext = data[2:]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext[:length]

    @staticmethod
    def ecdh_static(private_key, public_key) -> bytes:
        return private_key.exchange(ec.ECDH(), public_key)

    # -- firmas ECDSA ---------------------------------------------------
    @staticmethod
    def raw_to_der(raw: bytes) -> bytes:
        if len(raw) != 64:
            raise ValueError("firma raw de 64 bytes esperada")
        r = int.from_bytes(raw[:32], "big")
        s = int.from_bytes(raw[32:], "big")
        return encode_dss_signature(r, s)

    @staticmethod
    def der_to_raw(der: bytes) -> bytes:
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    # -- handshake ------------------------------------------------------
    def msg_challenge(self, message: bytes) -> bytes:
        data = message[4:-2]
        if len(data) != 4:
            raise BluettiError("challenge con longitud inesperada")
        self.unsecure_iv = hashlib.md5(data[::-1]).digest()
        self.unsecure_key = bytes(a ^ b for a, b in zip(self.unsecure_iv, LOCAL_AES_KEY))
        body = b"\x02\x04" + self.unsecure_iv[8:12]
        return KEX_MAGIC + body + _checksum(body)

    def msg_peer_pubkey(self, message: bytes) -> bytes:
        if self.unsecure_key is None or self.unsecure_iv is None:
            raise BluettiError("peer pubkey antes del challenge")
        data = message[4:-2]
        if len(data) != 128:
            raise BluettiError(f"peer pubkey con longitud inesperada: {len(data)}")
        peer_raw, signature = data[:64], data[64:]
        signed = peer_raw + self.unsecure_iv
        self._peer_signing_public.verify(
            self.raw_to_der(signature), signed, ec.ECDSA(hashes.SHA256())
        )
        self.peer_pub_raw = peer_raw

        self.my_private = ec.generate_private_key(ec.SECP256R1())
        self.my_public = self.my_private.public_key()
        my_raw = self.my_public.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )[1:]
        signing_key = ec.derive_private_key(
            int.from_bytes(PRIVATE_KEY_L1, "big"), ec.SECP256R1()
        )
        der_signature = signing_key.sign(
            my_raw + self.unsecure_iv, ec.ECDSA(hashes.SHA256())
        )
        raw_signature = self.der_to_raw(der_signature)
        body = b"\x05\x80" + my_raw + raw_signature
        inner = KEX_MAGIC + body + _checksum(body)
        return self.aes_encrypt(inner, self.unsecure_key, self.unsecure_iv)

    def msg_key_accepted(self, message: bytes) -> None:
        data = message[4:-2]
        if len(data) != 1 or data[0] != 0:
            raise BluettiError("confirmación de clave inesperada")
        if self.my_private is None or self.peer_pub_raw is None:
            raise BluettiError("confirmación de clave antes del intercambio")
        peer_public = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b"\x04" + self.peer_pub_raw
        )
        self.secure_key = self.my_private.exchange(ec.ECDH(), peer_public)

    # -- transporte -----------------------------------------------------
    def decrypt_transport(self, block: bytes) -> bytes:
        key, iv = self.get_key_iv()
        if key is None:
            raise BluettiError("sin clave para descifrar")
        return self.aes_decrypt(block, key, iv)

    def encrypt_transport(self, plain: bytes) -> bytes:
        if self.secure_key is None:
            raise BluettiError("canal cifrado no preparado")
        return self.aes_encrypt(plain, self.secure_key)


def _checksum(body: bytes) -> bytes:
    return sum(body).to_bytes(2, "big")


def is_pre_key(message: bytes | bytearray) -> bool:
    return len(message) >= 6 and bytes(message[:2]) == KEX_MAGIC


# -------------------------------------------------------------------- lectura


@dataclass
class Reading:
    percent: int = -1
    ac_out: int = -1
    dc_out: int = -1
    ac_in: int = -1
    dc_in: int = -1
    device_type: str = ""
    encrypted: bool = False
    error: str | None = None
    timestamp: float = 0.0
    address: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and self.percent >= 0

    @property
    def total_out(self) -> int:
        return max(0, self.ac_out) + max(0, self.dc_out)

    @property
    def total_in(self) -> int:
        return max(0, self.ac_in) + max(0, self.dc_in)

    @property
    def state(self) -> str:
        if self.error is not None:
            return "sin conexión"
        charging = self.total_in > 5
        consuming = self.total_out > 5
        if charging and consuming:
            return "entrada y salida"
        if charging:
            return "cargando"
        if consuming:
            return "descargando"
        return "en reposo"

    def as_dict(self) -> dict:
        now = time.time()
        return {
            "ok": self.ok,
            "battery_percent": self.percent if self.percent >= 0 else None,
            "output_watts": self.total_out if self.ok else None,
            "ac_output_watts": self.ac_out if self.ac_out >= 0 else None,
            "dc_output_watts": self.dc_out if self.dc_out >= 0 else None,
            "input_watts": self.total_in if self.ok else None,
            "ac_input_watts": self.ac_in if self.ac_in >= 0 else None,
            "dc_input_watts": self.dc_in if self.dc_in >= 0 else None,
            "state": self.state,
            "device_type": self.device_type or None,
            "encrypted": self.encrypted,
            "address": self.address,
            "error": self.error,
            "updated_at": iso_time(self.timestamp) if self.timestamp else None,
            "age_seconds": round(max(0.0, now - self.timestamp), 1) if self.timestamp else None,
        }


def iso_time(timestamp: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


class BluettiClient:
    """Cliente BLE de una sola lectura (conexión, handshake, registros)."""

    def __init__(self, crypto: Crypto | None = None) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.plain_messages: deque[bytes] = deque()
        self.crypto = crypto or Crypto()
        self.client: BleakClient | None = None
        self.encrypted_mode = False
        self.handshake_started = False
        self.disconnected = False
        self.raw_buffer = bytearray()
        self.encrypted_buffer = bytearray()

    # -- bucle de lectura ------------------------------------------------
    async def read(
        self,
        address: str,
        name: str = "",
        encrypted_hint: bool | None = None,
        timeout: float = READ_TIMEOUT,
    ) -> Reading:
        deadline = asyncio.get_running_loop().time() + timeout
        device = await self._find_device(address, name)
        self.client = BleakClient(device, disconnected_callback=self._on_disconnect)
        try:
            await asyncio.wait_for(self.client.connect(), timeout=15)
            await asyncio.wait_for(
                self.client.start_notify(NOTIFY_UUID, self._on_notify), timeout=10
            )
            encrypted = await self._establish(encrypted_hint, deadline)

            soc_body = await self._read_register(*READ_REGISTERS[0])
            percent = u16(soc_body)
            if not 0 <= percent <= 100:
                raise BluettiError("porcentaje de batería no válido")

            type_body = await self._read_register(*READ_REGISTERS[1])
            device_type = swap_string(type_body)
            if not is_valid_device_type(device_type):
                raise BluettiError(f"modelo no reconocido: {device_type!r}")

            reading = Reading(
                percent=percent,
                device_type=device_type,
                encrypted=encrypted,
                timestamp=time.time(),
                address=str(getattr(device, "address", address)).upper(),
            )
            reading.dc_out = u16(await self._read_register(*READ_REGISTERS[2]))
            reading.ac_out = u16(await self._read_register(*READ_REGISTERS[3]))
            reading.dc_in = u16(await self._read_register(*READ_REGISTERS[4]))
            reading.ac_in = u16(await self._read_register(*READ_REGISTERS[5]))
            reading.timestamp = time.time()
            return reading
        finally:
            try:
                await self.client.stop_notify(NOTIFY_UUID)
            except Exception:  # noqa: BLE001
                pass
            try:
                await self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.client = None

    # -- descubrimiento --------------------------------------------------
    async def _find_device(self, address: str, name: str):
        try:
            discovered = await BleakScanner.discover(timeout=SCAN_TIMEOUT, return_adv=True)
        except Exception as exc:  # noqa: BLE001
            raise BluettiError(f"no se pudo escanear Bluetooth: {exc}") from exc

        wanted = (address or "").upper()
        if wanted:
            for found_address, (device, _advertisement) in discovered.items():
                if found_address.upper() == wanted:
                    return device

        prefix = (name or "").strip()[:5].upper()
        candidates = []
        for found_address, (device, advertisement) in discovered.items():
            found_name = (device.name or advertisement.local_name or "").strip()
            if not found_name or not is_bluetti_name(found_name):
                continue
            if prefix and not found_name.upper().startswith(prefix):
                continue
            candidates.append((advertisement.rssi or -999, found_address, device))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][2]
        raise BluettiError("equipo no encontrado (¿encendido y cerca?)")

    # -- callbacks -------------------------------------------------------
    def _on_notify(self, _characteristic, data: bytearray) -> None:
        self.queue.put_nowait(bytes(data))

    def _on_disconnect(self, _client) -> None:
        self.disconnected = True
        self.queue.put_nowait(b"")

    # -- notificaciones --------------------------------------------------
    async def _next_notification(self, timeout: float) -> bytes | None:
        if timeout <= 0:
            return None
        try:
            message = await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        if message == b"":
            raise BluettiError("conexión BLE perdida")
        return message

    async def _next_plain(self, deadline: float) -> bytes | None:
        loop = asyncio.get_running_loop()
        while True:
            if self.plain_messages:
                return self.plain_messages.popleft()
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            message = await self._next_notification(remaining)
            if message is None:
                return None
            await self._handle_notification(message)

    async def _handle_notification(self, message: bytes) -> None:
        if is_pre_key(message):
            self.handshake_started = True
            self.raw_buffer.extend(message)
            while len(self.raw_buffer) >= 6:
                data_length = self.raw_buffer[3]
                expected = 6 + data_length
                if len(self.raw_buffer) < expected:
                    break
                frame = bytes(self.raw_buffer[:expected])
                self.raw_buffer = bytearray(self.raw_buffer[expected:])
                await self._handle_raw_kex(frame)
            return

        if self.handshake_started or self.encrypted_mode:
            self.encrypted_buffer.extend(message)
            while True:
                expected = self.crypto.expected_length(self.encrypted_buffer)
                if expected <= 0 or len(self.encrypted_buffer) < expected:
                    break
                block = bytes(self.encrypted_buffer[:expected])
                self.encrypted_buffer = bytearray(self.encrypted_buffer[expected:])
                plain = self.crypto.decrypt_transport(block)
                if is_pre_key(plain):
                    message_type = plain[2] & 0xFF
                    if message_type == TYPE_PEER_PUBKEY:
                        # El equipo también envía su clave pública cifrada con la
                        # clave temporal (no en claro).
                        reply = self.crypto.msg_peer_pubkey(plain)
                        await self._write(reply)
                    elif message_type == TYPE_PUBKEY_ACCEPTED:
                        self.crypto.msg_key_accepted(plain)
                else:
                    self.plain_messages.append(plain)
        else:
            self.plain_messages.append(message)

    async def _handle_raw_kex(self, frame: bytes) -> None:
        message_type = frame[2] & 0xFF
        reply = None
        if message_type == TYPE_CHALLENGE:
            reply = self.crypto.msg_challenge(frame)
        elif message_type == TYPE_PEER_PUBKEY:
            reply = self.crypto.msg_peer_pubkey(frame)
        if reply:
            await self._write(reply)

    async def _establish(self, hint: bool | None, deadline: float) -> bool:
        loop = asyncio.get_running_loop()
        if hint is False:
            self.encrypted_mode = False
            return False
        first_timeout = 8.0 if hint is True else 2.5
        first = await self._next_notification(first_timeout)
        if first is not None:
            await self._handle_notification(first)

        if self.handshake_started:
            handshake_deadline = min(deadline, loop.time() + 25.0)
            while not self.crypto.ready and loop.time() < handshake_deadline:
                message = await self._next_notification(
                    max(0.1, handshake_deadline - loop.time())
                )
                if message is None:
                    break
                await self._handle_notification(message)
            self.encrypted_mode = self.crypto.ready

        if self.encrypted_mode:
            return True
        if hint is True:
            raise BluettiError("el equipo no completó el canal cifrado")
        self.encrypted_mode = False
        return False

    # -- escritura -------------------------------------------------------
    async def _write(self, data: bytes) -> None:
        if self.client is None:
            raise BluettiError("conexión BLE cerrada")
        try:
            await asyncio.wait_for(
                self.client.write_gatt_char(WRITE_UUID, data, response=True),
                timeout=WRITE_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            raise BluettiError("escritura BLE: tiempo agotado") from exc
        except BleakError as exc:
            raise BluettiError(f"escritura BLE fallida: {exc}") from exc

    async def _read_register(self, address: int, quantity: int) -> bytes:
        request = modbus_read_request(address, quantity)
        payload = self.crypto.encrypt_transport(request) if self.encrypted_mode else request
        await self._write(payload)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + 6.0
        expected = 5 + quantity * 2
        buffer = bytearray()
        while loop.time() < deadline:
            part = await self._next_plain(deadline)
            if part is None:
                break
            buffer.extend(part)
            if len(buffer) >= expected:
                frame = bytes(buffer[:expected])
                rest = bytes(buffer[expected:])
                if rest:
                    self.plain_messages.appendleft(rest)
                body = parse_read_response(frame, quantity)
                if body is None:
                    raise BluettiError("respuesta MODBUS inválida")
                return body
        raise BluettiError(f"sin respuesta del equipo (registro {address})")


async def read_status(
    address: str,
    name: str = "",
    encrypted_hint: bool | None = None,
    timeout: float = READ_TIMEOUT,
) -> Reading:
    """Lee una vez y devuelve un Reading (con error incluido si falla)."""
    if not address and not name:
        return Reading(error="sin dispositivo configurado", timestamp=time.time())

    try:
        return await BluettiClient().read(address, name, encrypted_hint, timeout)
    except Exception as first_error:  # noqa: BLE001
        LOGGER.debug("Primer intento fallido: %s", first_error)
        if name:
            try:
                hit = await scan_for(name, timeout=6.0)
                if hit is not None and hit.address.upper() != (address or "").upper():
                    LOGGER.info("Dirección cambiada: %s -> %s", address, hit.address)
                    return await BluettiClient().read(
                        hit.address, hit.name, hit.encrypted, timeout
                    )
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("Reintento por nombre fallido: %s", exc)
        return Reading(error=str(first_error) or first_error.__class__.__name__, timestamp=time.time())
