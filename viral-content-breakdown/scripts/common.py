#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".flv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
TRANSCRIPT_EXTS = {".srt", ".vtt", ".ass", ".lrc", ".txt"}


@dataclass
class CmdResult:
    code: int
    stdout: str
    stderr: str
    argv: List[str]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if any(x in host for x in ["douyin.com", "iesdouyin.com"]):
        return "douyin"
    if any(x in host for x in ["xiaohongshu.com", "xhslink.com"]):
        return "xiaohongshu"
    return "unknown"


def slugify_url(url: str) -> str:
    parsed = urlparse(url)
    base = (parsed.netloc + parsed.path).strip("/")
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-").lower()
    if not base:
        base = "content"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base[:80]}-{stamp}"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_chmod_600(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def find_executable(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found

    # 常见用户安装路径兜底（例如 pip --user / homebrew）
    home = Path.home()
    candidates = [
        home / "Library/Python/3.9/bin" / name,
        home / ".local/bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ]
    for path in candidates:
        if path.exists() and path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def run_cmd(argv: List[str], cwd: Optional[Path] = None, timeout: Optional[int] = None) -> CmdResult:
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return CmdResult(proc.returncode, proc.stdout, proc.stderr, argv)


def classify_files(paths: List[Path]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {"video": [], "images": [], "audio": [], "transcript": [], "other": []}
    for p in paths:
        ext = p.suffix.lower()
        p_str = str(p)
        if ext in VIDEO_EXTS:
            out["video"].append(p_str)
        elif ext in IMAGE_EXTS:
            out["images"].append(p_str)
        elif ext in AUDIO_EXTS:
            out["audio"].append(p_str)
        elif ext in TRANSCRIPT_EXTS:
            out["transcript"].append(p_str)
        else:
            out["other"].append(p_str)
    return out


def prompt_yes_no(message: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            raw = input(f"{message} {suffix} ").strip().lower()
        except EOFError:
            # 非交互环境下回落到默认值，避免流水线卡死
            return default_yes
        if not raw:
            return default_yes
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("请输入 y 或 n")


def structured_error(code: str, reason: str, next_action: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": False,
        "error": {
            "code": code,
            "reason": reason,
            "next_action": next_action,
            "timestamp": utc_now_iso(),
        },
    }
    if extra:
        payload["error"].update(extra)
    return payload


def summarize_cmd(res: CmdResult) -> Dict[str, Any]:
    return {
        "argv": res.argv,
        "exit_code": res.code,
        "stdout_tail": res.stdout[-2000:],
        "stderr_tail": res.stderr[-2000:],
    }
