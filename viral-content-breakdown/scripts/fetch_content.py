#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from common import (
    classify_files,
    detect_platform,
    ensure_dir,
    find_executable,
    read_json,
    run_cmd,
    structured_error,
    summarize_cmd,
    utc_now_iso,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载抖音/小红书内容")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--session-file", help="session_bootstrap 生成的会话配置")
    parser.add_argument("--input-video", action="append", default=[], help="可选：直接使用本地视频（可重复）")
    parser.add_argument("--input-image", action="append", default=[], help="可选：直接使用本地图像（可重复）")
    parser.add_argument("--input-audio", action="append", default=[], help="可选：直接使用本地音频（可重复）")
    parser.add_argument("--input-transcript", action="append", default=[], help="可选：直接使用本地字幕/文本（可重复）")
    parser.add_argument("--quality", default="high")
    parser.add_argument("--result-file", help="结果 JSON 输出路径，默认 output-dir/fetch_result.json")
    return parser.parse_args()


def _all_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def _build_cookie_args(session: Dict[str, Any]) -> List[str]:
    if not session.get("ok"):
        return []
    cookies = session.get("cookies", {})
    cookie_file = cookies.get("cookies_file")
    from_browser = cookies.get("cookies_from_browser")
    if cookie_file and Path(cookie_file).exists():
        return ["--cookies", cookie_file]
    if from_browser:
        # yt-dlp: safari/chromium/chrome/firefox
        return ["--cookies-from-browser", from_browser]
    return []


def _normalize_content_url(url: str) -> Tuple[str, Optional[str]]:
    """
    标准化常见平台 URL 形态，减少下载器不支持 user+modal_id 这类链接导致的失败。
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    qs = parse_qs(parsed.query or "")

    if "douyin.com" in host:
        modal_id = qs.get("modal_id", [None])[0]
        if modal_id and path.startswith("/user/"):
            return f"https://www.douyin.com/video/{modal_id}", "converted_user_modal_to_video"

    return url, None


def _collect_manual_assets(args: argparse.Namespace) -> Dict[str, List[str]]:
    def _existing(paths: List[str]) -> List[str]:
        out: List[str] = []
        for raw in paths:
            p = Path(raw).expanduser().resolve()
            if p.exists() and p.is_file():
                out.append(str(p))
        return out

    return {
        "video": _existing(args.input_video or []),
        "images": _existing(args.input_image or []),
        "audio": _existing(args.input_audio or []),
        "transcript": _existing(args.input_transcript or []),
    }


def _looks_cookie_permission_error(text: str) -> bool:
    t = text.lower()
    return "cookies.binarycookies" in t or ("operation not permitted" in t and "cookie" in t)


def _looks_dns_error(text: str) -> bool:
    t = text.lower()
    patterns = [
        "nodename nor servname provided",
        "name or service not known",
        "temporary failure in name resolution",
        "failed to resolve",
    ]
    return any(p in t for p in patterns)


def _derive_failure_reason(adapter_attempts: List[Dict[str, Any]]) -> Tuple[str, str]:
    if not find_executable("yt-dlp"):
        return "yt-dlp 未安装", "先安装 yt-dlp（可用 python3 -m pip install --user yt-dlp）"

    stderr_all = "\n".join(
        str(x.get("result", {}).get("stderr_tail", "")) for x in adapter_attempts if isinstance(x, dict)
    )
    if _looks_dns_error(stderr_all):
        return (
            "网络或 DNS 无法解析平台域名",
            "检查当前环境网络/DNS；在可联网终端或代理环境重试",
        )
    if _looks_cookie_permission_error(stderr_all):
        return (
            "无权限读取浏览器 Cookies",
            "改用 Chrome 登录态或提供 --cookies 文件，避免 Safari Cookies 权限限制",
        )
    if "fresh cookies are needed" in stderr_all.lower():
        return (
            "平台要求更新登录态 Cookies",
            "先在浏览器打开目标视频页并保持登录，再重试；必要时提供 cookies 文件",
        )
    if "http error 403" in stderr_all.lower() or "forbidden" in stderr_all.lower():
        return "访问被拒绝（403）", "刷新登录态并重试，或确认内容是否仅自己可见"
    if "404" in stderr_all:
        return "内容不存在或已下线", "检查链接是否有效、内容是否被删除"

    return "下载失败或未识别到可分析媒体", "检查链接可访问性、登录状态，并确认 yt-dlp/专用下载器已安装"


def _cookie_arg_variants(session: Dict[str, Any], platform: str) -> List[Tuple[str, List[str]]]:
    variants: List[Tuple[str, List[str]]] = []

    session_args = _build_cookie_args(session)
    if session_args:
        variants.append(("session", session_args))

    preferred = ["chrome", "chromium", "firefox", "safari"]
    if platform == "xiaohongshu":
        preferred = ["chrome", "chromium", "safari", "firefox"]

    for browser in preferred:
        variants.append((f"browser:{browser}", ["--cookies-from-browser", browser]))

    variants.append(("no-cookies", []))

    dedup: List[Tuple[str, List[str]]] = []
    seen = set()
    for label, args in variants:
        key = tuple(args)
        if key in seen:
            continue
        seen.add(key)
        dedup.append((label, args))
    return dedup


def _run_yt_dlp(url: str, download_dir: Path, session: Dict[str, Any], platform: str) -> Tuple[bool, Dict[str, Any]]:
    exe = find_executable("yt-dlp")
    if not exe:
        return False, {"adapter": "yt-dlp", "error": "yt-dlp 未安装"}

    before = set(_all_files(download_dir))
    output_tmpl = str(download_dir / "%(id)s" / "%(title).120B.%(ext)s")
    base_cmd = [
        exe,
        "--no-progress",
        "--no-warnings",
        "--write-info-json",
        "--write-thumbnail",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "zh.*,en.*",
        "-o",
        output_tmpl,
    ]
    attempt_details: List[Dict[str, Any]] = []
    variants = _cookie_arg_variants(session, platform)
    for label, cookie_args in variants:
        cmd = [*base_cmd, *cookie_args, url]
        res = run_cmd(cmd)
        after = set(_all_files(download_dir))
        new_files = sorted([p for p in after - before], key=lambda p: str(p))
        detail = {
            "cookie_variant": label,
            "command": " ".join(shlex.quote(x) for x in cmd),
            "result": summarize_cmd(res),
            "new_files": [str(p) for p in new_files],
        }
        attempt_details.append(detail)
        if res.code == 0 and new_files:
            return True, {
                "adapter": "yt-dlp",
                "command": detail["command"],
                "result": detail["result"],
                "new_files": detail["new_files"],
                "attempt_variants": attempt_details,
            }

    last = attempt_details[-1] if attempt_details else {}
    return False, {
        "adapter": "yt-dlp",
        "command": last.get("command", ""),
        "result": last.get("result", {}),
        "new_files": last.get("new_files", []),
        "attempt_variants": attempt_details,
    }


def _run_xhs_specialized(url: str, download_dir: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    candidates: List[List[str]] = [
        ["xhs-downloader", "--url", url, "--output", str(download_dir)],
        ["rednote-video-assist", "--url", url, "--output", str(download_dir)],
        ["xhsdl", url, "--output", str(download_dir)],
    ]

    for cmd in candidates:
        exe = find_executable(cmd[0])
        if not exe:
            continue
        real_cmd = [exe, *cmd[1:]]
        before = set(_all_files(download_dir))
        res = run_cmd(real_cmd)
        after = set(_all_files(download_dir))
        new_files = sorted([p for p in after - before], key=lambda p: str(p))
        payload = {
            "adapter": "xhs-specialized",
            "adapter_bin": cmd[0],
            "command": " ".join(shlex.quote(x) for x in real_cmd),
            "result": summarize_cmd(res),
            "new_files": [str(p) for p in new_files],
        }
        if res.code == 0:
            return True, payload
    return False, None


def _infer_content_type(asset_index: Dict[str, List[str]]) -> str:
    if asset_index.get("video"):
        return "video"
    if asset_index.get("images"):
        return "image_post"
    return "unknown"


def main() -> int:
    args = parse_args()
    output_dir = ensure_dir(Path(args.output_dir).resolve())
    download_dir = ensure_dir(output_dir / "download")
    result_file = Path(args.result_file).resolve() if args.result_file else output_dir / "fetch_result.json"

    url = args.url.strip()
    platform = detect_platform(url)
    if platform == "unknown":
        err = structured_error(
            "UNSUPPORTED_PLATFORM",
            "仅支持抖音和小红书链接",
            "请提供 douyin.com / xiaohongshu.com / xhslink.com 链接",
            {"url": url},
        )
        write_json(result_file, err)
        print(result_file)
        return 1

    session: Dict[str, Any] = {}
    if args.session_file:
        session_path = Path(args.session_file)
        session = read_json(session_path, default={})

    adapter_attempts: List[Dict[str, Any]] = []
    success = False

    if platform == "xiaohongshu":
        ok, payload = _run_xhs_specialized(url, download_dir)
        if payload:
            adapter_attempts.append(payload)
        success = ok

    if not success:
        ok, payload = _run_yt_dlp(url, download_dir, session)
        adapter_attempts.append(payload)
        success = ok

    all_files = _all_files(download_dir)
    classified = classify_files(all_files)
    content_type = _infer_content_type(classified)

    if not success or content_type == "unknown":
        reason, next_action = _derive_failure_reason(adapter_attempts)
        err = structured_error(
            "DOWNLOAD_FAILED",
            reason,
            next_action,
            {
                "url": url,
                "platform": platform,
                "attempts": adapter_attempts,
                "download_dir": str(download_dir),
            },
        )
        write_json(result_file, err)
        print(result_file)
        return 1

    payload = {
        "ok": True,
        "meta": {
            "url": url,
            "platform": platform,
            "content_type": content_type,
            "fetched_at": utc_now_iso(),
            "quality": args.quality,
        },
        "asset_index": {
            "video": classified["video"],
            "images": classified["images"],
            "audio": classified["audio"],
            "transcript": classified["transcript"],
            "cover_text": [],
        },
        "artifacts": {
            "output_dir": str(output_dir),
            "download_dir": str(download_dir),
            "all_files": [str(p) for p in all_files],
        },
        "adapter_attempts": adapter_attempts,
    }

    write_json(result_file, payload)
    print(result_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
