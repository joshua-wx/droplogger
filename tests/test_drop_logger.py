"""
Tests for drop_logger.py

drop_logger.py is MicroPython firmware, so all hardware-specific modules
(utime, machine, icm20649, bmpxxx) must be replaced with mocks before the
module is imported.  The mocks are installed at module level so they are in
place for the single import that follows.
"""
import sys
import struct
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest

# ---------------------------------------------------------------------------
# Install MicroPython module stubs
# ---------------------------------------------------------------------------
# These must be present in sys.modules *before* drop_logger is imported so
# that "from machine import Pin, I2C" and similar statements resolve cleanly.

for _mod in ("utime", "machine", "icm20649", "bmpxxx"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import drop_logger  # noqa: E402  (must follow mock setup)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bmp_mock(pressure=1013.25):
    m = MagicMock()
    m.pressure = pressure
    return m


def _make_icm_mock(acceleration=(9.81, 0.0, 0.0), gyro=(0.0, 0.0, 0.0)):
    m = MagicMock()
    m.acceleration = acceleration
    m.gyro = gyro
    return m


def _make_boot_pin_mock(pressed=True):
    """Return a mock boot-pin that reports pressed (value=0) or not (value=1)."""
    m = MagicMock()
    m.value.return_value = 0 if pressed else 1
    return m


def _pin_factory(boot_pin_mock):
    """Return a Pin constructor that yields boot_pin_mock only for GPIO 0."""
    def factory(pin_num, *args, **kwargs):
        return boot_pin_mock if pin_num == 0 else MagicMock()
    return factory


@contextmanager
def _patched_hardware(bmp_mock, icm_mock, boot_pin_mock,
                      ticks_ms=0, ticks_diff=100):
    """Patch every hardware dependency inside drop_logger.main().

    MicroPython's open() treats "a" as binary append; CPython treats it as
    text.  We intercept open() inside drop_logger so that any call opening a
    .bin file uses "ab" instead of "a", matching the MicroPython behaviour.
    """
    icm20649_mod = MagicMock()
    icm20649_mod.ICM20649.return_value = icm_mock

    utime_mock = MagicMock()
    utime_mock.ticks_ms.return_value = ticks_ms
    utime_mock.ticks_diff.return_value = ticks_diff

    import builtins
    _real_open = builtins.open

    def _bin_open(file, mode="r", *args, **kwargs):
        if str(file).endswith(".bin") and mode == "a":
            mode = "ab"
        return _real_open(file, mode, *args, **kwargs)

    with patch.object(drop_logger, "Pin", side_effect=_pin_factory(boot_pin_mock)), \
         patch.object(drop_logger, "I2C", return_value=MagicMock()), \
         patch.object(drop_logger, "BMP581", return_value=bmp_mock), \
         patch.object(drop_logger, "icm20649", new=icm20649_mod), \
         patch.object(drop_logger, "utime", new=utime_mock), \
         patch.object(drop_logger, "machine"), \
         patch("drop_logger.open", side_effect=_bin_open):
        yield


# ---------------------------------------------------------------------------
# count_files()
# ---------------------------------------------------------------------------

class TestCountFiles:

    def test_counts_files_with_matching_extension(self, tmp_path):
        (tmp_path / "a.bin").write_bytes(b"")
        (tmp_path / "b.bin").write_bytes(b"")
        (tmp_path / "c.txt").write_bytes(b"")

        assert drop_logger.count_files(str(tmp_path), ".bin") == 2

    def test_empty_directory_returns_zero(self, tmp_path):
        assert drop_logger.count_files(str(tmp_path), ".bin") == 0

    def test_no_files_with_given_extension_returns_zero(self, tmp_path):
        (tmp_path / "a.csv").write_bytes(b"")
        assert drop_logger.count_files(str(tmp_path), ".bin") == 0

    def test_does_not_count_files_with_different_extension(self, tmp_path):
        (tmp_path / "a.bin").write_bytes(b"")
        (tmp_path / "b.csv").write_bytes(b"")
        (tmp_path / "c.txt").write_bytes(b"")

        assert drop_logger.count_files(str(tmp_path), ".bin") == 1


# ---------------------------------------------------------------------------
# Binary format constants
# ---------------------------------------------------------------------------

class TestBinaryFormat:

    def test_file_magic(self):
        assert drop_logger.FILE_MAGIC == b"DL01"

    def test_header_size_is_8_bytes(self):
        # '>4sf'  = 4-byte magic + 4-byte float32
        assert drop_logger.HEADER_SIZE == 8

    def test_row_size_is_16_bytes(self):
        # '>IiHhhh' = uint32 + int32 + uint16 + int16*3 = 4+4+2+2+2+2
        assert drop_logger.ROW_SIZE == 16

    def test_header_roundtrip(self):
        magic, pressure = struct.unpack(
            drop_logger.HEADER_FORMAT,
            struct.pack(drop_logger.HEADER_FORMAT, b"DL01", 1013.25),
        )
        assert magic == b"DL01"
        assert pressure == pytest.approx(1013.25, rel=1e-4)

    def test_row_roundtrip(self):
        row = (12345, -500, 982, 100, -200, 300)
        packed = struct.pack(drop_logger.ROW_FORMAT, *row)
        assert struct.unpack(drop_logger.ROW_FORMAT, packed) == row

    def test_a_mag_uses_unsigned_uint16(self):
        """ROW_FORMAT should use H (unsigned) for a_mag so values up to
        65535 (655.35 m/s²) can be represented without wrapping."""
        assert "H" in drop_logger.ROW_FORMAT

        # A value that would overflow int16 but fits uint16
        a_mag = 40000
        packed = struct.pack(drop_logger.ROW_FORMAT, 0, 0, a_mag, 0, 0, 0)
        assert struct.unpack(drop_logger.ROW_FORMAT, packed)[2] == a_mag


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:

    # -- File creation -------------------------------------------------------

    def test_creates_binary_file_in_data_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        bmp = _make_bmp_mock()
        icm = _make_icm_mock()
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=0), \
             _patched_hardware(bmp, icm, pin):
            drop_logger.main("mydevice")

        assert (tmp_path / "data" / "mydevice_1.bin").exists()

    def test_file_number_increments_based_on_existing_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        # Simulate 2 pre-existing .bin files in /data
        bmp = _make_bmp_mock()
        icm = _make_icm_mock()
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=2), \
             _patched_hardware(bmp, icm, pin):
            drop_logger.main("mydevice")

        assert (tmp_path / "data" / "mydevice_3.bin").exists()

    # -- Binary header -------------------------------------------------------

    def test_written_file_has_valid_magic_and_ref_pressure(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        ref_pressure = 1013.25
        bmp = _make_bmp_mock(pressure=ref_pressure)
        icm = _make_icm_mock()
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=0), \
             _patched_hardware(bmp, icm, pin):
            drop_logger.main("dev")

        data = (tmp_path / "data" / "dev_1.bin").read_bytes()
        magic, pressure = struct.unpack_from(drop_logger.HEADER_FORMAT, data, 0)
        assert magic == b"DL01"
        assert pressure == pytest.approx(ref_pressure, rel=1e-4)

    def test_file_contains_at_least_one_data_row(self, tmp_path, monkeypatch):
        """One sensor row must be written before the boot-pin break fires."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        bmp = _make_bmp_mock()
        icm = _make_icm_mock()
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=0), \
             _patched_hardware(bmp, icm, pin):
            drop_logger.main("dev")

        data = (tmp_path / "data" / "dev_1.bin").read_bytes()
        assert len(data) >= drop_logger.HEADER_SIZE + drop_logger.ROW_SIZE

    def test_data_row_encodes_gyro_values(self, tmp_path, monkeypatch):
        """Gyro readings must appear verbatim (rounded to int) in the row."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        bmp = _make_bmp_mock(pressure=1013.25)
        icm = _make_icm_mock(
            acceleration=(9.81, 0.0, 0.0),
            gyro=(100.0, -50.0, 25.0),
        )
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=0), \
             _patched_hardware(bmp, icm, pin, ticks_diff=1000):
            drop_logger.main("dev")

        data = (tmp_path / "data" / "dev_1.bin").read_bytes()
        _, _, _, gx, gy, gz = struct.unpack_from(
            drop_logger.ROW_FORMAT, data, drop_logger.HEADER_SIZE
        )
        assert gx == 100
        assert gy == -50
        assert gz == 25

    # -- Calibration ---------------------------------------------------------

    def test_reads_accel_calibration_from_config_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "accel_calibration.txt").write_text("9.80665")

        bmp = _make_bmp_mock()
        icm = _make_icm_mock()
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=0), \
             _patched_hardware(bmp, icm, pin):
            drop_logger.main("dev")  # must not raise

    def test_uses_default_calibration_when_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        # No config/ directory — OSError should be caught silently

        bmp = _make_bmp_mock()
        icm = _make_icm_mock()
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=0), \
             _patched_hardware(bmp, icm, pin):
            drop_logger.main("dev")  # must not raise

    def test_default_calibration_value_is_used_in_accel_encoding(self, tmp_path, monkeypatch):
        """With no calibration file the default (10.21) is used.  The scale
        factor 9.80665/10.21 should bring a reading of 10.21 m/s² back to
        9.81 m/s², encoding to 981 in the binary row."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()

        default_rest = drop_logger.default_a_mag_at_rest  # 10.21
        bmp = _make_bmp_mock(pressure=1013.25)
        # Feed a magnitude equal to the rest value so correction → ~9.81
        icm = _make_icm_mock(acceleration=(default_rest, 0.0, 0.0))
        pin = _make_boot_pin_mock(pressed=True)

        with patch.object(drop_logger, "count_files", return_value=0), \
             _patched_hardware(bmp, icm, pin, ticks_diff=0):
            drop_logger.main("dev")

        data = (tmp_path / "data" / "dev_1.bin").read_bytes()
        _, _, a_mag_enc, *_ = struct.unpack_from(
            drop_logger.ROW_FORMAT, data, drop_logger.HEADER_SIZE
        )
        # After scale correction a_mag ≈ 9.80665; encoded as round(9.80665*100) = 981
        assert a_mag_enc == 981
