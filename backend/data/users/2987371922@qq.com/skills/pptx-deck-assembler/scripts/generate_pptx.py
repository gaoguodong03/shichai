#!/usr/bin/env python3
"""Wrapper script to generate editable PPTX from deck.json."""
from pathlib import Path
import runpy
import sys


def main() -> int:
    src = Path(__file__).resolve().parents[2] / "ppt-outline-to-deck" / "scripts" / "generate_pptx.py"
    if not src.exists():
        print(f"ERROR: 缺少源脚本: {src}", file=sys.stderr)
        return 1
    glb = {"__name__": "__main__", "__file__": str(src)}
    runpy.run_path(str(src), init_globals=glb, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
