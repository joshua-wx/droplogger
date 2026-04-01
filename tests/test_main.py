"""
Tests for main.py

main.py is MicroPython firmware whose top-level code runs an infinite
while-loop the moment the module is imported.  To make it testable we:

  1. Replace all hardware modules in sys.modules before each import.
  2. Configure the ICM20649 mock so that the fall-detection break condition
     fires after exactly five loop iterations (acceleration below threshold).
  3. Mock drop_logger.main() so the logger itself does not run.

Each test deletes 'main' from sys.modules before importing so the
module-level code executes fresh with the desired mock configuration.

Limitations
-----------
The nested button-press blink loop (short vs long press) is tested by
carefully staging the sequence of boot_pin.value() return values and the
simulated elapsed time returned by time.ticks_diff().  Because all of this
state is controlled via mock side-effects the tests are somewhat sensitive
to the exact call order; if main.py's button-handling logic changes the
tests may need corresponding updates.
"""
import sys
import os
import importlib
from unittest.mock import MagicMock, call
import pytest

# conftest.py already adds scripts/ to sys.path


# ---------------------------------------------------------------------------
# Mock-setup helpers
# ---------------------------------------------------------------------------

def _install_mocks(acceleration=(0.0, 0.0, 0.0), boot_pin_values=None,
                   ticks_diff_value=100):
    """Install all module-level mocks required by main.py.

    Parameters
    ----------
    acceleration:
        Value returned by icm.acceleration on every loop iteration.
        (0, 0, 0) → a_total = 0 < threshold → fall detected after 5 iters.
        (9.81, 0, 0) → a_total ≈ 9.81 > threshold → no fall detection.
    boot_pin_values:
        Optional list used as side_effect for boot_pin.value().
        None → always returns 1 (not pressed).
    ticks_diff_value:
        Return value of time.ticks_diff(); controls short vs long press.
    """
    # Remove previously imported main so the loop re-runs cleanly
    sys.modules.pop("main", None)

    # ICM20649 instance
    icm_instance = MagicMock()
    icm_instance.acceleration = acceleration

    icm20649_mock = MagicMock()
    icm20649_mock.ICM20649.return_value = icm_instance

    # Boot-pin (GPIO 0)
    boot_pin = MagicMock()
    if boot_pin_values is not None:
        boot_pin.value.side_effect = boot_pin_values
    else:
        boot_pin.value.return_value = 1  # never pressed

    def pin_factory(pin_num, *args, **kwargs):
        return boot_pin if pin_num == 0 else MagicMock()

    machine_mock = MagicMock()
    machine_mock.Pin.side_effect = pin_factory

    # time mock — ticks_ms/ticks_diff are MicroPython extensions not in
    # standard library; mocking the whole module avoids AttributeError
    time_mock = MagicMock()
    time_mock.ticks_ms.return_value = 0
    time_mock.ticks_diff.return_value = ticks_diff_value
    time_mock.sleep = MagicMock()

    drop_logger_mock = MagicMock()
    file_server_mock = MagicMock()

    sys.modules["machine"] = machine_mock
    sys.modules["icm20649"] = icm20649_mock
    sys.modules["time"] = time_mock
    sys.modules["drop_logger"] = drop_logger_mock
    sys.modules["file_server"] = file_server_mock

    return {
        "machine": machine_mock,
        "icm": icm_instance,
        "icm20649": icm20649_mock,
        "boot_pin": boot_pin,
        "time": time_mock,
        "drop_logger": drop_logger_mock,
        "file_server": file_server_mock,
    }


def _run_main():
    """Import (re-import) main.py, executing its module-level loop."""
    import main  # noqa: F401
    return sys.modules["main"]


# ---------------------------------------------------------------------------
# Fall-detection tests
# ---------------------------------------------------------------------------

class TestFallDetection:

    def test_fall_triggers_drop_logger(self, tmp_path, monkeypatch):
        """Sustained low acceleration for ≥ fall_trigger_counter_limit
        iterations must call drop_logger.main()."""
        monkeypatch.chdir(tmp_path)
        # a_total = 0.0 < fall_trigger_a_threshold (5) → counter increments
        mocks = _install_mocks(acceleration=(0.0, 0.0, 0.0))

        _run_main()

        mocks["drop_logger"].main.assert_called_once()

    def test_fall_passes_device_name_from_config(self, tmp_path, monkeypatch):
        """drop_logger.main() must receive the name read from device_name.txt."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "device_name.txt").write_text("my-sensor")

        mocks = _install_mocks(acceleration=(0.0, 0.0, 0.0))

        _run_main()

        mocks["drop_logger"].main.assert_called_once_with("my-sensor")

    def test_fall_uses_default_device_name_when_config_missing(self, tmp_path, monkeypatch):
        """When device_name.txt is absent drop_logger.main() receives
        the hard-coded fallback name 'droplogger'."""
        monkeypatch.chdir(tmp_path)
        mocks = _install_mocks(acceleration=(0.0, 0.0, 0.0))

        _run_main()

        mocks["drop_logger"].main.assert_called_once_with("droplogger")

    def test_fall_counter_resets_after_high_acceleration(self, tmp_path, monkeypatch):
        """If a high-acceleration sample interrupts the sequence the counter
        must reset; the logger should only start after 5 *consecutive* low
        readings."""
        monkeypatch.chdir(tmp_path)

        # 4 low → counter = 4; 1 high → counter resets to 0;
        # 5 low → counter = 5 → fall triggered
        readings = (
            [(0.0, 0.0, 0.0)] * 4    # 4 consecutive low
            + [(9.81, 0.0, 0.0)]      # interrupt: counter reset
            + [(0.0, 0.0, 0.0)] * 5  # 5 consecutive low → triggers
        )

        mocks = _install_mocks()
        # Drive icm.acceleration from the readings list
        mocks["icm"].acceleration = readings[0]
        idx = [0]

        class _AccelDescriptor:
            def __get__(self, obj, objtype=None):
                v = readings[idx[0]] if idx[0] < len(readings) else readings[-1]
                idx[0] += 1
                return v

        type(mocks["icm"]).acceleration = _AccelDescriptor()

        _run_main()

        mocks["drop_logger"].main.assert_called_once()


# ---------------------------------------------------------------------------
# Button-press tests
# ---------------------------------------------------------------------------

class TestButtonPress:

    def test_short_press_triggers_drop_logger(self, tmp_path, monkeypatch):
        """A button press held for less than LONG_PRESS_MS (2000 ms) must
        call drop_logger.main()."""
        monkeypatch.chdir(tmp_path)

        # High acceleration keeps fall-detection inactive.
        # boot_pin sequence:
        #   call 1 – outer loop "if boot_pin.value() == 0" → 0 (pressed)
        #   call 2 – blink-loop "while boot_pin.value() == 0" → 0 (still held)
        #   call 3 – blink-loop → 1 (released)
        # ticks_diff → 100 ms < LONG_PRESS_MS (2000) → short press
        mocks = _install_mocks(
            acceleration=(9.81, 0.0, 0.0),
            boot_pin_values=[0, 0, 1],
            ticks_diff_value=100,
        )

        _run_main()

        mocks["drop_logger"].main.assert_called_once()
        mocks["file_server"].start_ap.assert_not_called()

    def test_long_press_starts_file_server(self, tmp_path, monkeypatch):
        """A button press held for ≥ LONG_PRESS_MS (2000 ms) must call
        file_server.start_ap() with the device name as the SSID."""
        monkeypatch.chdir(tmp_path)

        # boot_pin sequence:
        #   call 1 – outer loop → 0 (pressed)
        #   call 2 – blink-loop → 0 (held, first iteration)
        #   call 3 – blink-loop → 0 (held, second iteration)
        #   call 4 – blink-loop → 1 (released)
        # ticks_diff → 2100 ms ≥ LONG_PRESS_MS → long press
        mocks = _install_mocks(
            acceleration=(9.81, 0.0, 0.0),
            boot_pin_values=[0, 0, 0, 1],
            ticks_diff_value=2100,
        )

        _run_main()

        mocks["file_server"].start_ap.assert_called_once_with(
            ssid="droplogger", password="hailstone"
        )
        mocks["drop_logger"].main.assert_not_called()

    def test_long_press_uses_device_name_from_config(self, tmp_path, monkeypatch):
        """The SSID passed to file_server.start_ap() should match the name
        read from device_name.txt."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "device_name.txt").write_text("drop-unit-7")

        mocks = _install_mocks(
            acceleration=(9.81, 0.0, 0.0),
            boot_pin_values=[0, 0, 0, 1],
            ticks_diff_value=2100,
        )

        _run_main()

        mocks["file_server"].start_ap.assert_called_once_with(
            ssid="drop-unit-7", password="hailstone"
        )
