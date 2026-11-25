"""Pruebas del hilo de sondeo con una lectura simulada (sin BLE)."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from bluetti_tray import poller as poller_module
from bluetti_tray.ble import BluettiError
from bluetti_tray.config import Config
from bluetti_tray.poller import Poller, StatusStore
from bluetti_tray.status import Status


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class PollerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(address="AA:BB:CC:DD:EE:FF", poll_interval=600)
        self.store = StatusStore()
        self.events: list[Status] = []
        self.learned: list[bool | None] = []
        self.poller = Poller(
            self.config,
            self.store,
            on_status=self.events.append,
            on_learned_encryption=self.learned.append,
        )

    def tearDown(self) -> None:
        self.poller.stop()

    def test_successful_read(self):
        status = Status(battery_percent=66, ac_output_power=120, dc_output_power=4, online=True, updated_at=time.time())
        with mock.patch.object(poller_module, "read_status", return_value=status):
            self.poller.start()
            self.assertTrue(wait_for(lambda: len(self.events) >= 1))
        self.assertEqual(self.store.snapshot().battery_percent, 66)
        self.assertEqual(self.store.snapshot().total_output_power, 124)
        self.assertEqual(len(self.store.history()), 1)

    def test_learns_encryption_on_success(self):
        status = Status(
            battery_percent=50,
            ac_output_power=10,
            dc_output_power=0,
            online=True,
            encrypted=True,
            updated_at=time.time(),
        )
        with mock.patch.object(poller_module, "read_status", return_value=status):
            self.poller.start()
            self.assertTrue(wait_for(lambda: len(self.learned) >= 1))
        self.assertEqual(self.learned, [True])

    def test_demo_does_not_learn_encryption(self):
        demo = Status(battery_percent=50, online=True, source="demo", updated_at=time.time())
        with mock.patch.object(poller_module, "read_status", return_value=demo):
            self.poller.start()
            self.assertTrue(wait_for(lambda: len(self.events) >= 1))
        self.assertEqual(self.learned, [])

    def test_offline_keeps_last_values(self):
        online = Status(battery_percent=55, ac_output_power=80, dc_output_power=0, online=True, updated_at=time.time())
        calls = {"count": 0}

        def fake_read(*_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return online
            raise BluettiError("equipo no encontrado")

        with mock.patch.object(poller_module, "read_status", side_effect=fake_read):
            self.poller.start()
            self.assertTrue(wait_for(lambda: len(self.events) >= 1))
            self.poller.refresh_now()
            self.assertTrue(wait_for(lambda: len(self.events) >= 2))

        final = self.store.snapshot()
        self.assertFalse(final.online)
        self.assertEqual(final.battery_percent, 55)  # conserva la última lectura
        self.assertIn("no encontrado", final.error or "")

    def test_address_change_is_reported(self):
        addresses: list[str] = []
        status = Status(
            battery_percent=50,
            online=True,
            address="BB:BB:BB:BB:BB:BB",
            updated_at=time.time(),
        )
        poller = Poller(
            self.config,
            self.store,
            on_status=self.events.append,
            on_address=addresses.append,
        )
        self.poller = poller  # tearDown detiene este
        with mock.patch.object(poller_module, "read_status", return_value=status):
            poller.start()
            self.assertTrue(wait_for(lambda: len(addresses) >= 1))
            poller.stop()
        self.assertEqual(addresses, ["BB:BB:BB:BB:BB:BB"])

    def test_refresh_now_wakes_up(self):
        status = Status(battery_percent=50, online=True, updated_at=time.time())
        with mock.patch.object(poller_module, "read_status", return_value=status):
            self.poller.start()
            self.assertTrue(wait_for(lambda: len(self.events) >= 1))
            self.poller.refresh_now()
            self.assertTrue(wait_for(lambda: len(self.events) >= 2, timeout=5))
        self.assertGreaterEqual(len(self.events), 2)


if __name__ == "__main__":
    unittest.main()
