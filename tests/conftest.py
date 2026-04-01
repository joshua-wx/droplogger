import sys
import os

_root = os.path.join(os.path.dirname(__file__), '..')

# MicroPython firmware (drop_logger, main, etc.)
sys.path.insert(0, os.path.join(_root, 'scripts'))
# Desktop tools (unpack_droplogger_binary)
sys.path.insert(0, _root)
