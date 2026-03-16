"""
Unpack binary drop logger files (.bin) to CSV.
 
Usage:
    python unpack_droplogger_binary.py droplogger_data_1.bin
    python unpack_droplogger_binary.py droplogger_data_1.bin -o output.csv
    python unpack_droplogger_binary.py /path/to/folder/
    python unpack_droplogger_binary.py /path/to/folder/ --replace
 
Binary format (DL01):
    Header (8 bytes):  magic(4s) + ref_pressure(float32)
    Rows   (20 bytes): time_ms(uint32) + p_diff_mhPa(int32) + aX(int16) + aY(int16) 
                        + aZ(int16) + gX(int16) + gY(int16) + gZ(int16)
"""
 
import struct
import sys
import os
 
FILE_MAGIC = b'DL01'
HEADER_FORMAT = '>4sf'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 8 bytes
ROW_FORMAT = '>Iihhhhhh'
ROW_SIZE = struct.calcsize(ROW_FORMAT)        # 20 bytes
 
 
def unpack_file(bin_path, csv_path=None):
    """Unpack a single .bin file to CSV.
    
    Returns True on success, False on error (prints message but does not exit).
    """
    if csv_path is None:
        csv_path = os.path.splitext(bin_path)[0] + '.csv'
 
    with open(bin_path, 'rb') as f:
        data = f.read()
 
    # Parse header
    if len(data) < HEADER_SIZE:
        print(f"  Error: file too small ({len(data)} bytes)")
        return False
 
    magic, ref_pressure = struct.unpack_from(HEADER_FORMAT, data, 0)
    if magic != FILE_MAGIC:
        print(f"  Error: bad magic {magic!r}, expected {FILE_MAGIC!r}")
        return False
 
    # Parse rows
    payload = data[HEADER_SIZE:]
    n_rows = len(payload) // ROW_SIZE
    remainder = len(payload) % ROW_SIZE
 
    print(f"  File:             {bin_path}")
    print(f"  File size:        {len(data)} bytes")
    print(f"  Ref pressure:     {ref_pressure:.3f} hPa")
    print(f"  Rows:             {n_rows}")
    if remainder:
        print(f"  Warning: {remainder} trailing bytes (incomplete final row?)")
 
    with open(csv_path, 'w') as out:
        # Write header
        out.write("time(s),Pressure Difference(hPa),aX(ms^-2),aY(ms^-2),aZ(ms^-2),"
                  "gX(deg/s),gY(deg/s),gZ(deg/s)\n")
        # Write reference pressure on first line (matching original CSV convention)
        out.write(f"-0.001,{ref_pressure:.3f},,,,,,\n")
 
        for i in range(n_rows):
            offset = HEADER_SIZE + i * ROW_SIZE
            time_ms, p_diff, ax, ay, az, gx, gy, gz = struct.unpack_from(ROW_FORMAT, data, offset)
 
            seconds = time_ms / 1000.0
            pressure_diff = p_diff / 1000.0  # back to hPa
            ax_f = ax / 100.0                 # back to m/s²
            ay_f = ay / 100.0
            az_f = az / 100.0
 
            out.write(f"{seconds:.3f},{pressure_diff:.3f},"
                      f"{ax_f:.2f},{ay_f:.2f},{az_f:.2f},"
                      f"{gx},{gy},{gz}\n")
 
    csv_size = os.path.getsize(csv_path)
    print(f"  Output:           {csv_path} ({csv_size} bytes)")
    print(f"  Compression:      {len(data)} -> {csv_size} bytes CSV "
          f"(binary was {100*(1-len(data)/csv_size):.0f}% smaller)")
    return True


def unpack_folder(folder_path, replace=False):
    """Unpack all .bin files in a folder to CSV.
    
    Args:
        folder_path: Path to folder containing .bin files.
        replace:     If True, overwrite existing .csv files. If False, skip them.
    """
    bin_files = sorted(f for f in os.listdir(folder_path) if f.endswith('.bin'))

    if not bin_files:
        print(f"No .bin files found in {folder_path}")
        return

    print(f"Found {len(bin_files)} .bin file(s) in {folder_path}\n")

    converted = 0
    skipped = 0
    failed = 0

    for fname in bin_files:
        bin_path = os.path.join(folder_path, fname)
        csv_path = os.path.splitext(bin_path)[0] + '.csv'

        if os.path.exists(csv_path) and not replace:
            print(f"[SKIP] {fname}  ->  CSV already exists (use --replace to overwrite)")
            skipped += 1
            continue

        label = "[REPLACE]" if os.path.exists(csv_path) else "[CONVERT]"
        print(f"{label} {fname}")

        if unpack_file(bin_path, csv_path):
            converted += 1
        else:
            failed += 1
        print()

    print(f"Done: {converted} converted, {skipped} skipped, {failed} failed "
          f"(out of {len(bin_files)} files)")
 
 
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python unpack_droplogger_binary.py <file.bin> [-o output.csv]")
        print("  python unpack_droplogger_binary.py <folder/> [--replace]")
        print()
        print("Options:")
        print("  -o <path>    Output CSV path (single-file mode only)")
        print("  --replace    Overwrite existing CSV files (folder mode)")
        sys.exit(1)
 
    target = sys.argv[1]
    replace = '--replace' in sys.argv

    if os.path.isdir(target):
        unpack_folder(target, replace=replace)
    elif os.path.isfile(target):
        csv_path = None
        if '-o' in sys.argv:
            csv_path = sys.argv[sys.argv.index('-o') + 1]
        if not unpack_file(target, csv_path):
            sys.exit(1)
    else:
        print(f"Error: '{target}' is not a file or directory")
        sys.exit(1)