"""Pruebas sin hardware: parseo, validación, icono y configuración."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from bluetti_bt_lib.utils.bleak_client_mock import ClientMockNoEncryption

from bluetti_tray import ble
from bluetti_tray.config import Config
from bluetti_tray.demo import demo_status
from bluetti_tray.icon import render_icon, write_ico
from bluetti_tray.status import (
    MODE_DISCHARGING,
    MODE_PASSTHROUGH,
    Status,
    band,
    fmt_power,
    infer_mode,
    tooltip,
)


def make_mock(soc: int = 87) -> ClientMockNoEncryption:
    mock = ClientMockNoEncryption()
    mock.add_r_int(102, soc)
    mock.add_r_sstr(110, "AC180P", 6)
    mock.add_r_sn(116, 2300000000000)
    mock.add_r_int(140, 34)   # salida DC
    mock.add_r_int(142, 280)  # salida AC
    mock.add_r_int(144, 0)    # entrada DC
    mock.add_r_int(146, 120)  # entrada AC
    return mock


class DiscoveryMatchTest(unittest.TestCase):
    @staticmethod
    def _found(*entries):
        result = {}
        for address, name, rssi, manufacturer in entries:
            device = type("Device", (), {"name": name})()
            advertisement = type(
                "Adv",
                (),
                {
                    "local_name": "",
                    "rssi": rssi,
                    "manufacturer_data": manufacturer or {},
                },
            )()
            result[address] = (device, advertisement)
        return result

    def test_prefers_configured_address(self):
        found = self._found(
            ("AA:AA:AA:AA:AA:AA", "AC180P111", -50, {0x4C42: b"BLUETTI"}),
            ("BB:BB:BB:BB:BB:BB", "AC180P222", -70, {}),
        )
        cfg = Config(address="aa:aa:aa:aa:aa:aa", device_type="AC180P")
        target = ble._match_device(found, cfg)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.address, "AA:AA:AA:AA:AA:AA")
        self.assertFalse(target.encrypted)

    def test_falls_back_to_name_when_address_changed(self):
        found = self._found(("CC:CC:CC:CC:CC:CC", "AC180P2507003893321", -60, {0x4C42: b"BLUETT" + b"F"}))
        cfg = Config(address="FF:FF:FF:FF:FF:FF", device_name="AC180P2507003893321", device_type="AC180P")
        target = ble._match_device(found, cfg)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.address, "CC:CC:CC:CC:CC:CC")
        self.assertTrue(target.encrypted)

    def test_matches_by_model_prefix_without_name(self):
        found = self._found(("DD:DD:DD:DD:DD:DD", "AC180P999", -80, {}))
        cfg = Config(address="", device_name="", device_type="AC180P")
        target = ble._match_device(found, cfg)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.address, "DD:DD:DD:DD:DD:DD")

    def test_no_match(self):
        found = self._found(("EE:EE:EE:EE:EE:EE", "TV Samsung", -40, {}))
        cfg = Config(address="FF:FF:FF:FF:FF:FF", device_type="AC180P")
        self.assertIsNone(ble._match_device(found, cfg))


class ReadRegistersTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_ac180p_registers(self):
        mock = make_mock()
        data = await ble._read_registers(
            "00:11:22:33:44:55", "AC180P", False, ble_client=mock
        )
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["total_battery_percent"], 87)
        self.assertEqual(data["device_type"], "AC180P")
        self.assertEqual(data["dc_output_power"], 34)
        self.assertEqual(data["ac_output_power"], 280)
        self.assertEqual(data["ac_input_power"], 120)

        status = ble.status_from_data(data, Config(), encrypted=False, address="AA:BB:CC:DD:EE:FF")
        self.assertTrue(status.online)
        self.assertEqual(status.battery_percent, 87)
        self.assertEqual(status.total_output_power, 314)
        self.assertEqual(status.total_input_power, 120)
        self.assertEqual(status.mode, MODE_PASSTHROUGH)
        self.assertEqual(status.device_type, "AC180P")
        self.assertEqual(status.address, "AA:BB:CC:DD:EE:FF")

    async def test_invalid_payload_rejected(self):
        mock = ClientMockNoEncryption()
        mock.add_r_int(102, 150)  # SOC imposible
        data = await ble._read_registers(
            "00:11:22:33:44:55", "AC180P", False, ble_client=mock
        )
        self.assertFalse(ble._valid_payload(data))

    def test_encryption_from_manufacturer_data(self):
        self.assertIs(
            ble.encryption_from_manufacturer_data({0x4C42: b"BLUETTI\x01\x02"}), False
        )
        self.assertIs(
            ble.encryption_from_manufacturer_data({0x4C42: b"BLUETTF\x01"}), True
        )
        self.assertIsNone(ble.encryption_from_manufacturer_data({}))
        self.assertIsNone(ble.encryption_from_manufacturer_data(None))
        self.assertIsNone(ble.encryption_from_manufacturer_data({7: b"OTRO"}))

    def test_supported_types_are_v2_only(self):
        self.assertIn("AC180P", ble.SUPPORTED_TYPES)
        self.assertIn("AC70", ble.SUPPORTED_TYPES)
        self.assertNotIn("EB3A", ble.SUPPORTED_TYPES)
        self.assertNotIn("AC200M", ble.SUPPORTED_TYPES)

    def test_device_type_resolution(self):
        for name in ("AC180P", "ac180p", " Handsfree 1 "):
            self.assertIsNotNone(ble._build_device(name))
        with self.assertRaises(ble.BluettiError):
            ble._build_device("NO-EXISTE")

    def test_config_keeps_device_type_case(self):
        self.assertEqual(Config(device_type="Handsfree 1").normalized().device_type, "Handsfree 1")
        self.assertEqual(Config(device_type="  ").normalized().device_type, "AC180P")

    def test_encryption_attempt_order(self):
        cfg = Config(encryption="auto")
        self.assertEqual(ble._encryption_attempts(cfg, None), [False, True])
        self.assertEqual(ble._encryption_attempts(cfg, True), [True])
        self.assertEqual(ble._encryption_attempts(Config(learned_encryption=True), None), [True])
        self.assertEqual(ble._encryption_attempts(Config(encryption="off"), True), [False])
        self.assertEqual(ble._encryption_attempts(Config(encryption="on"), False), [True])


class StatusTest(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(infer_mode(0, 0, 0, 0), "idle")
        self.assertEqual(infer_mode(280, 34, 0, 0), MODE_DISCHARGING)
        self.assertEqual(infer_mode(0, 0, 500, 0), "charging")
        self.assertEqual(infer_mode(20, 0, 500, 0), MODE_PASSTHROUGH)
        self.assertEqual(infer_mode(None, None, None, None), "unknown")

    def test_formatting(self):
        self.assertEqual(fmt_power(1234), "1.234 W")
        self.assertEqual(fmt_power(None), "—")
        self.assertEqual(band(80), "good")
        self.assertEqual(band(30), "warn")
        self.assertEqual(band(10), "bad")

    def test_tooltip_is_short(self):
        status = Status(
            battery_percent=87,
            ac_output_power=280,
            dc_output_power=34,
            ac_input_power=0,
            dc_input_power=0,
            device_name="AC180P",
            online=True,
            updated_at=1.0,
        )
        text = tooltip(status)
        self.assertLessEqual(len(text), 120)
        self.assertIn("87 %", text)
        self.assertIn("314 W", text)

    def test_tooltip_offline(self):
        text = tooltip(Status(online=False, error="equipo no encontrado"))
        self.assertIn("sin conexión", text)

    def test_demo_status_plausible(self):
        for t in range(0, 121, 7):
            status = demo_status(float(t))
            self.assertTrue(0 <= (status.battery_percent or 0) <= 100)
            self.assertGreaterEqual(status.total_output_power or 0, 0)


class IconTest(unittest.TestCase):
    def test_render_all_modes_and_sizes(self):
        status = demo_status(5.0)
        for metric in ("percent", "power", "both"):
            for size in (16, 24, 32, 48, 64):
                image = render_icon(status, metric=metric, size=size)
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.mode, "RGBA")

    def test_offline_icon(self):
        image = render_icon(Status(online=False), size=32)
        self.assertEqual(image.size, (32, 32))

    def test_write_ico(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.ico"
            write_ico(path)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 1000)


class ConfigTest(unittest.TestCase):
    def test_roundtrip_and_clamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            cfg = Config(address="aa:bb:cc:dd:ee:ff", poll_interval=5, icon_metric="xx")
            cfg.save(path)
            loaded = Config.load(path)
            self.assertEqual(loaded.address, "AA:BB:CC:DD:EE:FF")
            self.assertEqual(loaded.poll_interval, 10)
            self.assertEqual(loaded.icon_metric, "percent")

    def test_missing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = Config.load(Path(tmp) / "nope.json")
            self.assertEqual(loaded.device_type, "AC180P")

    def test_corrupt_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{no es json", encoding="utf-8")
            loaded = Config.load(path)
            self.assertEqual(loaded.poll_interval, 60)


if __name__ == "__main__":
    unittest.main()
