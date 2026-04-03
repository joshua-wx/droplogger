"""
Tests for unpack_droplogger_binary.py

This module is pure Python and requires no hardware mocks.
Binary payloads are constructed using the module's own format constants so
the tests always stay in sync with the implementation.
"""
import struct
import pytest

import unpack_droplogger_binary as udb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_binary(ref_pressure, rows):
    """Build a valid DL01 binary payload from a reference pressure and row tuples.

    Each row is (time_ms, p_diff_mhPa, a_mag_cm_s2, gx, gy, gz).
    Uses the same format constants as the unpack module.
    """
    data = struct.pack(udb.HEADER_FORMAT, udb.FILE_MAGIC, ref_pressure)
    for row in rows:
        data += struct.pack(udb.ROW_FORMAT, *row)
    return data


# ---------------------------------------------------------------------------
# unpack_file() tests
# ---------------------------------------------------------------------------

class TestUnpackFile:

    def test_valid_single_row_returns_true(self, tmp_path):
        bin_file = tmp_path / "test.bin"
        bin_file.write_bytes(make_binary(1013.25, [(1000, 500, 981, 10, -5, 3)]))

        result = udb.unpack_file(str(bin_file), str(tmp_path / "out.csv"))

        assert result is True

    def test_valid_single_row_csv_structure(self, tmp_path):
        ref_pressure = 1013.25
        bin_file = tmp_path / "test.bin"
        bin_file.write_bytes(make_binary(ref_pressure, [(1000, 500, 981, 10, -5, 3)]))
        csv_file = tmp_path / "out.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        lines = csv_file.read_text().splitlines()
        # Header row
        assert lines[0] == (
            "time(s),Pressure Difference(hPa),a(ms^-2),"
            "gX(deg/s),gY(deg/s),gZ(deg/s)"
        )
        # Reference pressure sentinel row
        assert lines[1].startswith("-0.001")
        assert f"{ref_pressure:.3f}" in lines[1]
        # First data row: 1000 ms -> 1.000 s, 500 mhPa -> 0.500 hPa, 981 -> 9.81 m/s²
        assert lines[2] == "1.000,0.500,9.81,10,-5,3"

    def test_reference_row_has_expected_field_count(self, tmp_path):
        ref_pressure = 1013.25
        bin_file = tmp_path / "test.bin"
        bin_file.write_bytes(make_binary(ref_pressure, [(1000, 0, 981, 0, 0, 0)]))
        csv_file = tmp_path / "out.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        second_line = csv_file.read_text().splitlines()[1]
        assert second_line == "-0.001,1013.250,,,,"
        assert len(second_line.split(',')) == 6

    def test_multiple_rows_all_written(self, tmp_path):
        rows = [
            (0,    0,    981,  0,  0,  0),
            (1000, 100,  990,  1,  2,  3),
            (2000, -200, 970, -1, -2, -3),
        ]
        bin_file = tmp_path / "test.bin"
        bin_file.write_bytes(make_binary(1000.0, rows))
        csv_file = tmp_path / "out.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        lines = csv_file.read_text().splitlines()
        # header + ref-pressure + 3 data rows
        assert len(lines) == 5
        assert lines[2] == "0.000,0.000,9.81,0,0,0"
        assert lines[3] == "1.000,0.100,9.90,1,2,3"
        assert lines[4] == "2.000,-0.200,9.70,-1,-2,-3"

    def test_file_too_small_returns_false(self, tmp_path):
        bin_file = tmp_path / "small.bin"
        bin_file.write_bytes(b"DL")  # 2 bytes < HEADER_SIZE (8)

        result = udb.unpack_file(str(bin_file), str(tmp_path / "out.csv"))

        assert result is False

    def test_bad_magic_returns_false(self, tmp_path):
        bin_file = tmp_path / "bad.bin"
        bin_file.write_bytes(struct.pack(udb.HEADER_FORMAT, b"XXXX", 1013.25))

        result = udb.unpack_file(str(bin_file), str(tmp_path / "out.csv"))

        assert result is False

    def test_default_output_path_derived_from_input(self, tmp_path):
        bin_file = tmp_path / "mylog.bin"
        bin_file.write_bytes(make_binary(1013.25, [(0, 0, 981, 0, 0, 0)]))

        udb.unpack_file(str(bin_file))  # no explicit csv_path

        assert (tmp_path / "mylog.csv").exists()

    def test_empty_payload_produces_only_header_lines(self, tmp_path):
        """A file with a valid header but zero rows should write only the two
        header/reference lines and return True."""
        bin_file = tmp_path / "empty.bin"
        bin_file.write_bytes(make_binary(1013.25, []))
        csv_file = tmp_path / "empty.csv"

        result = udb.unpack_file(str(bin_file), str(csv_file))

        assert result is True
        lines = csv_file.read_text().splitlines()
        assert len(lines) == 2  # column header + ref-pressure line

    def test_trailing_bytes_warns_but_succeeds(self, tmp_path, capsys):
        """Extra bytes at the end (incomplete trailing row) should print a
        warning but still return True and write the complete rows."""
        data = make_binary(1013.25, [(1000, 0, 981, 0, 0, 0)]) + b"\x00\x01\x02"
        bin_file = tmp_path / "partial.bin"
        bin_file.write_bytes(data)

        result = udb.unpack_file(str(bin_file), str(tmp_path / "out.csv"))

        assert result is True
        assert "Warning" in capsys.readouterr().out

    def test_time_decoded_to_seconds(self, tmp_path):
        bin_file = tmp_path / "t.bin"
        bin_file.write_bytes(make_binary(1013.25, [(5500, 0, 981, 0, 0, 0)]))
        csv_file = tmp_path / "t.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        time_col = csv_file.read_text().splitlines()[2].split(",")[0]
        assert time_col == "5.500"

    def test_pressure_decoded_from_milli_hpa(self, tmp_path):
        """p_diff stored as milli-hPa (×1000) must be divided back on read."""
        bin_file = tmp_path / "p.bin"
        bin_file.write_bytes(make_binary(1013.25, [(0, 1500, 981, 0, 0, 0)]))
        csv_file = tmp_path / "p.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        p_col = csv_file.read_text().splitlines()[2].split(",")[1]
        assert p_col == "1.500"

    def test_acceleration_decoded_from_centi_m_s2(self, tmp_path):
        """a_mag stored as a_mag×100 must be divided back on read."""
        bin_file = tmp_path / "a.bin"
        bin_file.write_bytes(make_binary(1013.25, [(0, 0, 981, 0, 0, 0)]))
        csv_file = tmp_path / "a.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        a_col = csv_file.read_text().splitlines()[2].split(",")[2]
        assert a_col == "9.81"

    def test_negative_pressure_diff(self, tmp_path):
        """Negative pressure differences (ascent) must round-trip correctly."""
        bin_file = tmp_path / "neg.bin"
        bin_file.write_bytes(make_binary(1013.25, [(0, -2000, 981, 0, 0, 0)]))
        csv_file = tmp_path / "neg.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        p_col = csv_file.read_text().splitlines()[2].split(",")[1]
        assert p_col == "-2.000"

    def test_gyro_values_written_as_integers(self, tmp_path):
        bin_file = tmp_path / "g.bin"
        bin_file.write_bytes(make_binary(1013.25, [(0, 0, 981, 120, -340, 56)]))
        csv_file = tmp_path / "g.csv"

        udb.unpack_file(str(bin_file), str(csv_file))

        parts = csv_file.read_text().splitlines()[2].split(",")
        assert parts[3] == "120"
        assert parts[4] == "-340"
        assert parts[5] == "56"


# ---------------------------------------------------------------------------
# unpack_folder() tests
# ---------------------------------------------------------------------------

class TestUnpackFolder:

    def test_no_bin_files_prints_message(self, tmp_path, capsys):
        udb.unpack_folder(str(tmp_path))
        assert "No .bin files found" in capsys.readouterr().out

    def test_converts_bin_file_to_csv(self, tmp_path):
        (tmp_path / "log.bin").write_bytes(make_binary(1013.25, [(0, 0, 981, 0, 0, 0)]))

        udb.unpack_folder(str(tmp_path))

        assert (tmp_path / "log.csv").exists()

    def test_skips_existing_csv_by_default(self, tmp_path, capsys):
        (tmp_path / "log.bin").write_bytes(make_binary(1013.25, []))
        (tmp_path / "log.csv").write_text("sentinel")

        udb.unpack_folder(str(tmp_path), replace=False)

        assert (tmp_path / "log.csv").read_text() == "sentinel"
        assert "SKIP" in capsys.readouterr().out

    def test_replace_flag_overwrites_existing_csv(self, tmp_path):
        (tmp_path / "log.bin").write_bytes(make_binary(1013.25, []))
        (tmp_path / "log.csv").write_text("sentinel")

        udb.unpack_folder(str(tmp_path), replace=True)

        assert (tmp_path / "log.csv").read_text() != "sentinel"

    def test_multiple_bin_files_all_converted(self, tmp_path):
        for i in range(3):
            (tmp_path / f"log_{i}.bin").write_bytes(make_binary(1013.25, []))

        udb.unpack_folder(str(tmp_path))

        assert len(list(tmp_path.glob("*.csv"))) == 3

    def test_summary_counts_are_correct(self, tmp_path, capsys):
        # 2 .bin files; 1 already has a .csv → expect 1 converted, 1 skipped
        (tmp_path / "a.bin").write_bytes(make_binary(1013.25, []))
        (tmp_path / "b.bin").write_bytes(make_binary(1013.25, []))
        (tmp_path / "a.csv").write_text("existing")

        udb.unpack_folder(str(tmp_path), replace=False)

        out = capsys.readouterr().out
        assert "1 converted" in out
        assert "1 skipped" in out


# ---------------------------------------------------------------------------
# Format consistency tests
# ---------------------------------------------------------------------------

class TestFormatConsistency:
    """Verify format constants and document the H vs h discrepancy between
    drop_logger.py (writer) and unpack_droplogger_binary.py (reader)."""

    def test_file_magic(self):
        assert udb.FILE_MAGIC == b"DL01"

    def test_header_size_is_8_bytes(self):
        # '>4sf' = 4-byte magic + 4-byte float32 = 8 bytes
        assert udb.HEADER_SIZE == 8

    def test_row_size_is_16_bytes(self):
        # '>Iihhhh' = uint32 + int32 + int16*4 = 4+4+2+2+2+2 = 16 bytes
        assert udb.ROW_SIZE == 16

    def test_a_mag_h_vs_H_compatible_for_realistic_values(self):
        """drop_logger.py packs a_mag as H (uint16); unpack uses h (int16).

        For all realistic sensor values (ICM20649 max ~16 g ≈ 157 m/s²,
        encoded as 15700) both formats produce identical byte representations
        because 15700 < 32767 (int16 max).  This test documents and verifies
        that compatibility.
        """
        dl_row_format = ">IiHhhh"   # drop_logger writer format
        udb_row_format = ">Iihhhh"  # unpack reader format

        a_mag_encoded = 15700  # 157.00 m/s² * 100 — near ICM20649 maximum

        packed = struct.pack(dl_row_format, 1000, 0, a_mag_encoded, 0, 0, 0)
        _, _, a_decoded, *_ = struct.unpack(udb_row_format, packed)

        # Unsigned 15700 and signed 15700 are the same bytes → identical result
        assert a_decoded == a_mag_encoded

    def test_a_mag_H_vs_h_diverge_above_int16_max(self):
        """Values > 32767 (> 327.67 m/s², far beyond any real sensor reading)
        would be misread if the unpack format is not updated to match H.
        This test documents the potential failure mode."""
        dl_row_format = ">IiHhhh"
        udb_row_format = ">Iihhhh"

        a_mag_encoded = 40000  # hypothetical value beyond int16 range

        packed = struct.pack(dl_row_format, 0, 0, a_mag_encoded, 0, 0, 0)
        _, _, a_decoded, *_ = struct.unpack(udb_row_format, packed)

        # Signed interpretation wraps: 40000 - 65536 = -25536
        assert a_decoded != a_mag_encoded
        assert a_decoded == a_mag_encoded - 65536
