"""paths.py -- where the editor finds the game files.

SSF2T_ROM_DIR   folder with ssf2t.zip, ssf2t.key, ssf2t_data.bin and
                ssf2t_opcodes.bin (default: the folder that contains the editor)
SSF2T_DATA      the raw program image (default: <ROM_DIR>/ssf2t_data.bin)
SSF2T_OPCODES   the decrypted unmodified image (default: <ROM_DIR>/ssf2t_opcodes.bin)
"""
import os

EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
ROM_DIR = os.environ.get("SSF2T_ROM_DIR") or os.path.dirname(EDITOR_DIR)
DATA_BIN = os.environ.get("SSF2T_DATA") or os.path.join(ROM_DIR, "ssf2t_data.bin")
# the decrypted reference image of the unmodified game: always from the ROM folder
# (SSF2T_DATA may point at a patched copy elsewhere)
OPCODES_BIN = os.environ.get("SSF2T_OPCODES") or os.path.join(ROM_DIR, "ssf2t_opcodes.bin")
