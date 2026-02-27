#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wrapper for douyin-downloader")
    p.add_argument("--cmd", help="可选：传入要执行的原始命令，例如 'python main.py --help'")
    p.add_argument("--dry-run", action="store_true", help="只打印执行计划")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    plan = {
        "repo": "douyin-downloader",
        "source": "https://github.com/jiji262/douyin-downloader",
        "latest_hash": "unknown",
        "cmd": args.cmd,
    }
    if args.dry_run or not args.cmd:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    proc = subprocess.run(args.cmd, shell=True)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
