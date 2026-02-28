#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

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
    parser = argparse.ArgumentParser(description="下载抖音/小红书/公众号内容")
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
    if "xhslink.com" in host:
        return url, "xhs_short_link_detected"

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
        ["rednotevideoassist", "--url", url, "--output", str(download_dir)],
        ["xhsdl", url, "--output", str(download_dir)],
        ["res-downloader", "--url", url, "--output", str(download_dir)],
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
        if res.code == 0 and new_files:
            return True, payload
    return False, None


def _run_douyin_specialized(url: str, download_dir: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    candidates: List[List[str]] = [
        ["douyin-downloader", "--url", url, "--output", str(download_dir)],
        ["res-downloader", "--url", url, "--output", str(download_dir)],
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
            "adapter": "douyin-specialized",
            "adapter_bin": cmd[0],
            "command": " ".join(shlex.quote(x) for x in real_cmd),
            "result": summarize_cmd(res),
            "new_files": [str(p) for p in new_files],
        }
        if res.code == 0 and new_files:
            return True, payload
    return False, None


def _run_wechat_specialized(url: str, download_dir: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    candidates: List[List[str]] = [
        ["wechat-article-exporter", "--url", url, "--output", str(download_dir)],
        ["res-downloader", "--url", url, "--output", str(download_dir)],
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
            "adapter": "wechat-specialized",
            "adapter_bin": cmd[0],
            "command": " ".join(shlex.quote(x) for x in real_cmd),
            "result": summarize_cmd(res),
            "new_files": [str(p) for p in new_files],
        }
        if res.code == 0 and new_files:
            return True, payload
    return False, None


def _extract_first(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    if not m:
        return ""
    return html.unescape((m.group(1) or "").strip())


def _html_to_text(raw: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"</p\s*>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _run_wechat_html_fallback(url: str, download_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    req = Request(url, headers=headers)
    before = set(_all_files(download_dir))
    try:
        with urlopen(req, timeout=20) as resp:
            html_raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return False, {
            "adapter": "wechat-html-fallback",
            "error": str(exc),
            "new_files": [],
            "result": {"exit_code": 1, "stderr_tail": str(exc), "stdout_tail": ""},
        }

    article_html = download_dir / "article.html"
    article_html.write_text(html_raw, encoding="utf-8")

    title = _extract_first(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_raw, re.IGNORECASE)
    if not title:
        title = _extract_first(r"<title>([^<]+)</title>", html_raw, re.IGNORECASE)
    desc = _extract_first(r'<meta\s+name="description"\s+content="([^"]+)"', html_raw, re.IGNORECASE)
    if not desc:
        desc = _extract_first(r'var\s+msg_desc\s*=\s*"([^"]*)"', html_raw)
    kws = _extract_first(r'<meta\s+name="keywords"\s+content="([^"]+)"', html_raw, re.IGNORECASE)
    tags = [x.strip() for x in re.split(r"[,，\s]+", kws) if x.strip()][:20]

    content_html = _extract_first(r'<div[^>]+id="js_content"[^>]*>([\s\S]*?)</div>', html_raw, re.IGNORECASE)
    body_text = _html_to_text(content_html or desc or "")
    if not body_text and desc:
        body_text = desc
    if not body_text and title:
        body_text = title

    article_txt = download_dir / "article_body.txt"
    article_txt.write_text(body_text, encoding="utf-8")

    cover = _extract_first(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_raw, re.IGNORECASE)
    cover_stored = ""
    if cover:
        try:
            with urlopen(Request(cover, headers=headers), timeout=15) as resp:
                data = resp.read()
            ext = ".jpg"
            if ".png" in cover.lower():
                ext = ".png"
            cover_path = download_dir / f"cover{ext}"
            cover_path.write_bytes(data)
            cover_stored = str(cover_path)
        except Exception:
            cover_stored = ""

    publish_ts = _extract_first(r"\bct\s*=\s*['\"]?(\d{10})['\"]?", html_raw)
    publish_date = ""
    if publish_ts:
        try:
            ts = int(publish_ts)
            publish_date = f"{ts}"
        except Exception:
            publish_date = ""

    info = {
        "title": title,
        "description": body_text[:2000],
        "tags": tags,
        "platform": "wechat_mp",
        "uploader": _extract_first(r'var\s+nickname\s*=\s*"([^"]*)"', html_raw),
        "webpage_url": url,
        "publish_timestamp": publish_date,
        "view_count": None,
        "like_count": None,
        "comment_count": None,
        "cover_url": cover,
        "cover_local_file": cover_stored,
    }
    info_path = download_dir / "wechat_article.info.json"
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    after = set(_all_files(download_dir))
    new_files = sorted([p for p in after - before], key=lambda p: str(p))
    return True, {
        "adapter": "wechat-html-fallback",
        "command": "urllib.request.urlopen",
        "result": {"exit_code": 0, "stdout_tail": "ok", "stderr_tail": ""},
        "new_files": [str(p) for p in new_files],
    }


def _pick_int(*values: Any) -> Optional[int]:
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if not s:
            continue
        s = re.sub(r"[^\d]", "", s)
        if s.isdigit():
            return int(s)
    return None


def _collect_info_jsons(files: List[Path]) -> List[Path]:
    out: List[Path] = []
    for p in files:
        if p.suffix.lower() != ".json":
            continue
        name = p.name.lower()
        if name.endswith(".info.json") or "article.info" in name:
            out.append(p)
    return out


def _extract_metadata(files: List[Path], platform: str) -> Dict[str, Any]:
    post_content: Dict[str, Any] = {"title": "", "body": "", "tags": []}
    metrics: Dict[str, Optional[int]] = {"likes": None, "comments": None, "plays": None}
    publish_at: str = ""

    for info_path in _collect_info_jsons(files):
        try:
            data = read_json(info_path, default={})
        except Exception:
            continue
        title = str(data.get("title", "") or data.get("fulltitle", "")).strip()
        body = str(data.get("description", "") or data.get("desc", "")).strip()
        raw_tags = data.get("tags")
        if not isinstance(raw_tags, list):
            raw_tags = data.get("categories") if isinstance(data.get("categories"), list) else []
        tags = [str(x).strip() for x in raw_tags if str(x).strip()][:30]

        if title and not post_content["title"]:
            post_content["title"] = title
        if body and not post_content["body"]:
            post_content["body"] = body
        if tags and not post_content["tags"]:
            post_content["tags"] = tags

        likes = _pick_int(data.get("like_count"), data.get("digg_count"), data.get("likes"))
        comments = _pick_int(data.get("comment_count"), data.get("comments_count"), data.get("comments"))
        plays = _pick_int(data.get("view_count"), data.get("play_count"), data.get("plays"))
        if metrics["likes"] is None and likes is not None:
            metrics["likes"] = likes
        if metrics["comments"] is None and comments is not None:
            metrics["comments"] = comments
        if metrics["plays"] is None and plays is not None:
            metrics["plays"] = plays

        publish_raw = (
            str(data.get("upload_date", "")).strip()
            or str(data.get("release_date", "")).strip()
            or str(data.get("timestamp", "")).strip()
            or str(data.get("publish_timestamp", "")).strip()
        )
        if publish_raw and not publish_at:
            publish_at = publish_raw

    if platform == "wechat_mp" and not post_content["title"]:
        for p in files:
            if p.name == "article_body.txt":
                text = p.read_text(encoding="utf-8", errors="ignore").strip()
                if text:
                    post_content["body"] = text[:5000]
                    post_content["title"] = text.splitlines()[0][:80]
                    break

    if not post_content["tags"]:
        tag_pool: List[str] = []
        source_text = f"{post_content['title']} {post_content['body']}"
        for m in re.finditer(r"#([A-Za-z0-9_\u4e00-\u9fa5]{2,30})", source_text):
            tag_pool.append(m.group(1))
        post_content["tags"] = tag_pool[:15]

    return {
        "post_content": post_content,
        "engagement_metrics": metrics,
        "published_at": publish_at,
    }


def _infer_content_type(asset_index: Dict[str, List[str]]) -> str:
    if asset_index.get("video"):
        return "video"
    if asset_index.get("images"):
        return "image_post"
    if asset_index.get("transcript"):
        return "article"
    return "unknown"


def main() -> int:
    args = parse_args()
    output_dir = ensure_dir(Path(args.output_dir).resolve())
    download_dir = ensure_dir(output_dir / "download")
    result_file = Path(args.result_file).resolve() if args.result_file else output_dir / "fetch_result.json"

    raw_url = args.url.strip()
    url, normalize_note = _normalize_content_url(raw_url)
    platform = detect_platform(url)
    if platform == "unknown":
        err = structured_error(
            "UNSUPPORTED_PLATFORM",
            "仅支持抖音、小红书、微信公众号链接",
            "请提供 douyin.com / xiaohongshu.com / xhslink.com / mp.weixin.qq.com 链接",
            {"url": raw_url},
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

    manual_assets = _collect_manual_assets(args)

    if platform == "wechat_mp":
        ok, payload = _run_wechat_specialized(url, download_dir)
        if payload:
            adapter_attempts.append(payload)
        success = ok

    if platform == "xiaohongshu":
        ok, payload = _run_xhs_specialized(url, download_dir)
        if payload:
            adapter_attempts.append(payload)
        success = success or ok

    if platform == "douyin":
        ok, payload = _run_douyin_specialized(url, download_dir)
        if payload:
            adapter_attempts.append(payload)
        success = success or ok

    if not success and platform in {"douyin", "xiaohongshu"}:
        ok, payload = _run_yt_dlp(url, download_dir, session, platform)
        adapter_attempts.append(payload)
        success = ok

    if platform == "xiaohongshu":
        # 小红书图文常含正文 JSON，若没有媒体也允许继续信号层处理
        if not success:
            info_files = [p for p in _all_files(download_dir) if p.name.endswith(".info.json")]
            if info_files:
                success = True

    if platform == "wechat_mp" and not success:
        ok, payload = _run_wechat_html_fallback(url, download_dir)
        adapter_attempts.append(payload)
        success = ok

    all_files = _all_files(download_dir)
    manual_paths = [Path(p) for key in manual_assets for p in manual_assets[key]]
    all_files = sorted(list({*all_files, *manual_paths}), key=lambda p: str(p))
    classified = classify_files(all_files)
    content_type = _infer_content_type(classified)
    metadata = _extract_metadata(all_files, platform)

    if not success and content_type == "unknown":
        reason, next_action = _derive_failure_reason(adapter_attempts)
        err = structured_error(
            "DOWNLOAD_FAILED",
            reason,
            next_action,
            {
                "url": raw_url,
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
            "url": raw_url,
            "normalized_url": url,
            "platform": platform,
            "content_type": content_type,
            "fetched_at": utc_now_iso(),
            "published_at": metadata.get("published_at", ""),
            "quality": args.quality,
            "url_normalized_note": normalize_note or "",
        },
        "asset_index": {
            "video": classified["video"],
            "images": classified["images"],
            "audio": classified["audio"],
            "transcript": classified["transcript"],
            "cover_text": [],
        },
        "post_content": metadata.get("post_content", {"title": "", "body": "", "tags": []}),
        "engagement_metrics": metadata.get("engagement_metrics", {"likes": None, "comments": None, "plays": None}),
        "artifacts": {
            "output_dir": str(output_dir),
            "download_dir": str(download_dir),
            "all_files": [str(p) for p in all_files],
            "manual_assets": manual_assets,
        },
        "adapter_attempts": adapter_attempts,
    }

    write_json(result_file, payload)
    print(result_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
