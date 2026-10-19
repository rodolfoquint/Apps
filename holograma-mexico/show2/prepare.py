#!/usr/bin/env python3
"""Show 2 version of show/prepare.py: writes cut-outs and line art to show2/assets/.

  python3 show2/prepare.py SRC NAME [--color R,G,B] [--size 1024] [--circle]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "show"))
import prepare  # noqa: E402

prepare.HERE = HERE

if __name__ == "__main__":
    prepare.main()
