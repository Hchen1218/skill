#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python smart_stitch.py <skill_dir>", file=sys.stderr)
        return 1
    suite = Path(__file__).resolve().parent / "github_skills_suite.py"
    cmd = [sys.executable, str(suite), "evolve-stitch", *sys.argv[1:]]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
