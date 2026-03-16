#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("02_run_computation.py")), run_name="__main__")
