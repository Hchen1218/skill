#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Tuple

from common import detect_platform, safe_chmod_600, structured_error, utc_now_iso, write_json

DEFAULT_LOGIN_URLS: Dict[str, str] = {
    "douyin": "https://www.douyin.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/",
    "unknown": "https://www.douyin.com/",
}


def _open_browser(url: str, browser: str) -> Tuple[bool, str]:
    if browser == "safari":
        proc = subprocess.run(["open", "-a", "Safari", url], check=False, text=True, capture_output=True)
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stderr or proc.stdout).strip()
    if browser == "chromium":
        # macOS 常见 Chrome 名称
        proc = subprocess.run(["open", "-a", "Google Chrome", url], check=False, text=True, capture_output=True)
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stderr or proc.stdout).strip()
    proc = subprocess.run(["open", url], check=False, text=True, capture_output=True)
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="扫码登录并保存会话配置")
    parser.add_argument("--url", help="内容链接，用于自动判断平台")
    parser.add_argument("--platform", choices=["auto", "douyin", "xiaohongshu"], default="auto")
    parser.add_argument("--browser", choices=["safari", "chromium"], default="safari")
    parser.add_argument("--session-mode", choices=["qr-login"], default="qr-login")
    parser.add_argument("--session-file", required=True, help="会话文件输出路径（json）")
    parser.add_argument("--non-interactive", action="store_true", help="非交互模式，禁用输入")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session_file = Path(args.session_file).expanduser().resolve()
    session_file.parent.mkdir(parents=True, exist_ok=True)

    platform = args.platform
    if platform == "auto":
        platform = detect_platform(args.url or "")

    login_url = DEFAULT_LOGIN_URLS.get(platform, DEFAULT_LOGIN_URLS["unknown"])

    print(f"[session] 打开浏览器进行扫码登录: {login_url}")
    opened, open_msg = _open_browser(login_url, args.browser)
    if not opened:
        print(f"[session] 浏览器启动失败，继续执行：{open_msg}")

    cookies_file = None
    if not args.non_interactive:
        try:
            input("[session] 请在浏览器中完成登录，然后回到终端按 Enter 继续...")
            raw = input(
                "[session] 如果你有 cookies 文件（Netscape 格式），请输入路径；没有则直接回车：\n> "
            ).strip()
        except EOFError:
            err = structured_error(
                "INTERACTIVE_INPUT_UNAVAILABLE",
                "当前环境无法进行终端交互输入",
                "请改用 --non-interactive，或在可交互终端中运行",
            )
            write_json(session_file, err)
            print("[session] 无法读取交互输入，已写入错误到 session 文件")
            return 1
        if raw:
            src = Path(raw).expanduser()
            if src.exists() and src.is_file():
                dst = session_file.parent / "cookies.txt"
                shutil.copy2(src, dst)
                safe_chmod_600(dst)
                cookies_file = str(dst)
            else:
                err = structured_error(
                    "INVALID_COOKIE_FILE",
                    f"cookies 文件不存在: {src}",
                    "检查路径后重新运行 session_bootstrap.py",
                )
                write_json(session_file, err)
                print("[session] cookies 文件路径无效，已写入错误到 session 文件")
                return 1

    cookie_browser = args.browser
    if cookie_browser == "chromium":
        cookie_browser = "chrome"

    session_payload = {
        "ok": True,
        "session_mode": args.session_mode,
        "platform": platform,
        "browser": args.browser,
        "created_at": utc_now_iso(),
        "cookies": {
            "source": "cookies_file" if cookies_file else "browser_session",
            "cookies_file": cookies_file,
            "cookies_from_browser": cookie_browser if not cookies_file else None,
        },
        "notes": [
            "若下载失败，请先刷新登录态后重试。",
            "Safari 模式通常建议配合 cookies 文件提高成功率。",
            f"browser_opened={opened}",
        ],
    }
    write_json(session_file, session_payload)
    safe_chmod_600(session_file)
    print(f"[session] 会话配置已保存: {session_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
