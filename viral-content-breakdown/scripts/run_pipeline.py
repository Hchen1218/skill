#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from common import (
    detect_platform,
    ensure_dir,
    prompt_yes_no,
    read_json,
    slugify_url,
    structured_error,
    utc_now_iso,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="viral-content-breakdown 一键流水线")
    parser.add_argument("--url", required=True, help="抖音/小红书/公众号单链接")
    parser.add_argument("--save-artifacts", choices=["ask", "always", "never"], default="ask")
    parser.add_argument("--output-dir", help="默认 ./viral_breakdowns/<slug>/")
    parser.add_argument("--browser", choices=["safari", "chromium"], default="safari")
    parser.add_argument("--session-mode", choices=["qr-login"], default="qr-login")
    parser.add_argument("--quality", default="high")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--skip-session", action="store_true", help="跳过扫码阶段，复用已有 session")
    parser.add_argument("--session-file", help="可选：复用指定 session.json 路径")
    parser.add_argument("--non-interactive", action="store_true", help="非交互模式（自动跳过输入提示）")
    return parser.parse_args()


def _script_path(name: str) -> Path:
    return Path(__file__).resolve().parent / name


def _run_step(cmd: List[str], step: str, run_meta: Dict[str, object]) -> None:
    print(f"[pipeline] {step}...")
    proc = subprocess.run(cmd, text=True, capture_output=True)
    run_meta.setdefault("steps", []).append(
        {
            "step": step,
            "exit_code": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
            "cmd": cmd,
        }
    )
    if proc.returncode != 0:
        raise RuntimeError(f"步骤失败: {step}\n{proc.stderr.strip() or proc.stdout.strip()}")


def _cleanup_for_never(output_dir: Path) -> None:
    keep_names = {"report.json", "report.md", "run_meta.json", "error.json"}
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name in keep_names:
            continue
        path.unlink(missing_ok=True)

    # 删除空目录
    for p in sorted(output_dir.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass


def _sanitize_summary(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\\/:*?\"<>|]+", "-", text)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff\-_ ]+", "-", text)
    text = text.strip(" .-_")
    if not text:
        text = "content"
    return text[:40]


def _derive_named_prefix(report: Dict[str, object], url: str) -> str:
    meta = report.get("meta", {}) if isinstance(report.get("meta"), dict) else {}
    post = report.get("post_content", {}) if isinstance(report.get("post_content"), dict) else {}
    cover = report.get("cover_title", {}) if isinstance(report.get("cover_title"), dict) else {}
    fetched_at = str(meta.get("fetched_at", ""))[:10]
    date_part = fetched_at.replace("-", "")
    if not date_part or len(date_part) != 8:
        date_part = utc_now_iso()[:10].replace("-", "")
    summary = _sanitize_summary(str(post.get("title", "")))
    if summary == "content":
        summary = _sanitize_summary(str(cover.get("text", "")))
    if summary == "content":
        summary = _sanitize_summary(slugify_url(url).rsplit("-", 1)[0])
    return f"{date_part}-{summary}"


def _export_named_reports(output_dir: Path, report: Dict[str, object], url: str) -> Dict[str, str]:
    root = ensure_dir(Path.cwd() / "viral_breakdowns")
    prefix = _derive_named_prefix(report, url)
    json_src = output_dir / "report.json"
    md_src = output_dir / "report.md"
    json_dst = root / f"{prefix}.json"
    md_dst = root / f"{prefix}.md"

    idx = 2
    while json_dst.exists() or md_dst.exists():
        json_dst = root / f"{prefix}-{idx}.json"
        md_dst = root / f"{prefix}-{idx}.md"
        idx += 1

    if json_src.exists():
        shutil.copy2(json_src, json_dst)
    if md_src.exists():
        shutil.copy2(md_src, md_dst)
    return {"json": str(json_dst), "markdown": str(md_dst)}


def main() -> int:
    args = parse_args()
    platform = detect_platform(args.url)
    if platform == "unknown":
        print("仅支持抖音/小红书/公众号链接")
        return 1

    non_interactive = args.non_interactive or (not sys.stdin.isatty())
    save_artifacts = args.save_artifacts
    if save_artifacts == "ask":
        if non_interactive:
            # 自动化/Agent 场景默认保留，避免阻塞
            save_artifacts = "always"
        else:
            keep = prompt_yes_no("是否保存下载素材（视频/图片/帧/音频）？", default_yes=True)
            save_artifacts = "always" if keep else "never"

    if args.output_dir:
        output_dir = ensure_dir(Path(args.output_dir).expanduser().resolve())
    else:
        output_dir = ensure_dir(Path.cwd() / "viral_breakdowns" / slugify_url(args.url))

    run_meta: Dict[str, object] = {
        "url": args.url,
        "platform": platform,
        "started_at": utc_now_iso(),
        "save_artifacts": save_artifacts,
        "non_interactive": non_interactive,
        "output_dir": str(output_dir),
        "steps": [],
    }
    run_meta_path = output_dir / "run_meta.json"

    try:
        if args.session_file:
            session_file = Path(args.session_file).expanduser().resolve()
            ensure_dir(session_file.parent)
        else:
            session_dir = ensure_dir(output_dir / "session")
            session_file = session_dir / "session.json"

        if not args.skip_session and not session_file.exists():
            cmd = [
                sys.executable,
                str(_script_path("session_bootstrap.py")),
                "--url",
                args.url,
                "--platform",
                platform,
                "--browser",
                args.browser,
                "--session-mode",
                args.session_mode,
                "--session-file",
                str(session_file),
            ]
            if non_interactive:
                cmd.append("--non-interactive")
            _run_step(
                cmd,
                "session_bootstrap",
                run_meta,
            )

        fetch_result = output_dir / "fetch_result.json"
        _run_step(
            [
                sys.executable,
                str(_script_path("fetch_content.py")),
                "--url",
                args.url,
                "--output-dir",
                str(output_dir),
                "--session-file",
                str(session_file),
                "--quality",
                args.quality,
                "--result-file",
                str(fetch_result),
            ],
            "fetch_content",
            run_meta,
        )

        signals_file = output_dir / "signals.json"
        _run_step(
            [
                sys.executable,
                str(_script_path("extract_signals.py")),
                "--fetch-result",
                str(fetch_result),
                "--output-dir",
                str(output_dir),
                "--result-file",
                str(signals_file),
            ],
            "extract_signals",
            run_meta,
        )

        report_file = output_dir / "report.json"
        markdown_file = output_dir / "report.md"
        _run_step(
            [
                sys.executable,
                str(_script_path("analyze_content.py")),
                "--signals",
                str(signals_file),
                "--output",
                str(report_file),
                "--markdown-output",
                str(markdown_file),
                "--model",
                args.model,
            ],
            "analyze_content",
            run_meta,
        )

        if save_artifacts == "never":
            # 保留 report + run_meta；其余素材清理
            _cleanup_for_never(output_dir)

        run_meta["finished_at"] = utc_now_iso()
        run_meta["ok"] = True
        report = read_json(report_file, default={})
        run_meta["named_outputs"] = _export_named_reports(output_dir, report, args.url)
        write_json(run_meta_path, run_meta)

        print("[pipeline] 完成")
        print(f"[pipeline] 报告: {report_file}")
        print(f"[pipeline] Markdown: {markdown_file}")
        print(f"[pipeline] 导出 JSON: {run_meta.get('named_outputs', {}).get('json', '')}")
        print(f"[pipeline] 导出 MD: {run_meta.get('named_outputs', {}).get('markdown', '')}")
        print(f"[pipeline] 模式: {report.get('meta', {}).get('analysis_mode', 'unknown')}")
        return 0

    except Exception as exc:
        err = structured_error(
            "PIPELINE_FAILED",
            str(exc),
            "查看 run_meta.json 与步骤 stderr，修复后重试。",
            {"output_dir": str(output_dir)},
        )
        error_file = output_dir / "error.json"
        write_json(error_file, err)
        run_meta["ok"] = False
        run_meta["finished_at"] = utc_now_iso()
        run_meta["error_file"] = str(error_file)
        run_meta["error"] = str(exc)
        write_json(run_meta_path, run_meta)
        print(f"[pipeline] 失败，详情: {error_file}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
