#!/usr/bin/env python3
"""Show 2 ("Un dia en Mexico", for the large fan): the same commands as show/build.py,
working on show2/ (pieces, assets, transitions, show.json) and writing to out-show2/.

  python3 show2/build.py --stills 05-huichol 0.5,2,4,6,8,10,11.5
  python3 show2/build.py 05-huichol
  python3 show2/build.py --show [--size 1600]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "show"))
import build  # noqa: E402

build.HERE = HERE
build.OUT = HERE.parent / "out-show2"

if __name__ == "__main__":
    build.main()
