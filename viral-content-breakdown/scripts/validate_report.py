#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_TOP_LEVEL = [
    "meta",
    "asset_index",
    "engagement_metrics",
    "visual_specs",
    "post_content",
    "hook",
    "script_structure",
    "narrative_pattern",
    "cover_title",
    "voiceover_copy",
    "production_method_inference",
    "virality_drivers",
    "adaptation_ideas",
    "page_breakdown",
    "structure_summary",
    "design_pattern",
    "blank_or_shell_frames",
    "limitations",
    "confidence_overall",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验 viral-content-breakdown 的 report.json 是否满足核心契约")
    parser.add_argument("--report", required=True, help="report.json 路径")
    parser.add_argument("--expected-platform", help="可选：期望的平台，例如 douyin/xiaohongshu/wechat_mp")
    parser.add_argument("--expected-content-type", help="可选：期望的内容类型，例如 video/image_post/article")
    parser.add_argument("--result-file", help="可选：将检查结果写入 JSON 文件")
    return parser.parse_args()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _add_check(checks: List[Dict[str, Any]], text: str, passed: bool, evidence: str) -> None:
    checks.append({"text": text, "passed": passed, "evidence": evidence})


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _has_nonempty_text(obj: Any, key: str) -> bool:
    return isinstance(obj, dict) and bool(_string(obj.get(key, "")).strip())


def _check_evidence_list(obj: Any) -> bool:
    return isinstance(obj, list) and any(isinstance(item, dict) and _string(item.get("snippet", "")).strip() for item in obj)


def main() -> int:
    args = parse_args()
    report_path = Path(args.report).expanduser().resolve()

    if not report_path.exists():
        result = {
            "expectations": [
                {
                    "text": "report.json 文件存在",
                    "passed": False,
                    "evidence": f"未找到文件: {report_path}",
                }
            ],
            "summary": {"passed": 0, "failed": 1, "total": 1, "pass_rate": 0.0},
        }
        if args.result_file:
            Path(args.result_file).expanduser().resolve().write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    report = _load_json(report_path)
    checks: List[Dict[str, Any]] = []

    meta = report.get("meta", {}) if isinstance(report.get("meta", {}), dict) else {}
    asset_index = report.get("asset_index", {}) if isinstance(report.get("asset_index", {}), dict) else {}
    hook = report.get("hook", {}) if isinstance(report.get("hook", {}), dict) else {}
    post_content = report.get("post_content", {}) if isinstance(report.get("post_content", {}), dict) else {}
    production_methods = report.get("production_method_inference", [])
    virality_drivers = report.get("virality_drivers", [])
    adaptation_ideas = report.get("adaptation_ideas", [])
    limitations = report.get("limitations", [])
    page_breakdown = report.get("page_breakdown", [])
    structure_summary = report.get("structure_summary", {}) if isinstance(report.get("structure_summary", {}), dict) else {}
    design_pattern = report.get("design_pattern", {}) if isinstance(report.get("design_pattern", {}), dict) else {}

    missing_top = [key for key in REQUIRED_TOP_LEVEL if key not in report]
    _add_check(
        checks,
        "顶层字段完整",
        not missing_top,
        "缺失字段: " + ", ".join(missing_top) if missing_top else "全部核心字段都存在",
    )

    _add_check(
        checks,
        "meta.language 为 zh-CN",
        meta.get("language") == "zh-CN",
        f"当前值: {meta.get('language')}",
    )

    _add_check(
        checks,
        "meta 中保留 fetched_at、published_at、analyzed_at",
        all(key in meta for key in ["fetched_at", "published_at", "analyzed_at"]),
        f"meta keys: {sorted(meta.keys())}",
    )

    if args.expected_platform:
        _add_check(
            checks,
            "平台识别正确",
            meta.get("platform") == args.expected_platform,
            f"期望 {args.expected_platform}，实际 {meta.get('platform')}",
        )

    if args.expected_content_type:
        _add_check(
            checks,
            "内容类型识别正确",
            meta.get("content_type") == args.expected_content_type,
            f"期望 {args.expected_content_type}，实际 {meta.get('content_type')}",
        )

    _add_check(
        checks,
        "标题、正文、hook 至少有可读内容",
        _has_nonempty_text(post_content, "title") or _has_nonempty_text(post_content, "body"),
        f"title={bool(_string(post_content.get('title')).strip())}, body={bool(_string(post_content.get('body')).strip())}",
    )
    _add_check(
        checks,
        "hook 含文本和 evidence",
        _has_nonempty_text(hook, "text") and _check_evidence_list(hook.get("evidence")),
        f"hook.text={_string(hook.get('text'))[:80]}, evidence_count={len(hook.get('evidence', [])) if isinstance(hook.get('evidence'), list) else 0}",
    )

    methods_ok = (
        isinstance(production_methods, list)
        and len(production_methods) == 3
        and all(isinstance(item, dict) and "confidence" in item for item in production_methods)
    )
    _add_check(
        checks,
        "production_method_inference 输出 Top3 且都带 confidence",
        methods_ok,
        f"当前条数: {len(production_methods) if isinstance(production_methods, list) else 'not_list'}",
    )

    drivers_ok = isinstance(virality_drivers, list) and bool(virality_drivers) and all(
        isinstance(item, dict) and _check_evidence_list(item.get("evidence")) for item in virality_drivers
    )
    _add_check(
        checks,
        "virality_drivers 非空且每条都带 evidence",
        drivers_ok,
        f"driver_count={len(virality_drivers) if isinstance(virality_drivers, list) else 'not_list'}",
    )

    ideas_ok = isinstance(adaptation_ideas, list) and len(adaptation_ideas) >= 2 and all(
        isinstance(item, dict) and _string(item.get("idea", "")).strip() and _string(item.get("rationale", "")).strip()
        for item in adaptation_ideas
    )
    _add_check(
        checks,
        "adaptation_ideas 至少有 2 条且包含 idea+rationale",
        ideas_ok,
        f"idea_count={len(adaptation_ideas) if isinstance(adaptation_ideas, list) else 'not_list'}",
    )

    _add_check(
        checks,
        "limitations 字段存在且为列表",
        isinstance(limitations, list),
        f"limitations_count={len(limitations) if isinstance(limitations, list) else 'not_list'}",
    )

    content_type = args.expected_content_type or meta.get("content_type")
    if content_type == "image_post":
        page_ok = isinstance(page_breakdown, list) and bool(page_breakdown)
        _add_check(
            checks,
            "小红书图文包含逐页 page_breakdown",
            page_ok,
            f"page_breakdown_count={len(page_breakdown) if isinstance(page_breakdown, list) else 'not_list'}",
        )
        fields_ok = page_ok and all(
            isinstance(item, dict)
            and all(key in item for key in ["page", "page_type", "core_role", "design_elements", "conversion_goal"])
            for item in page_breakdown
        )
        _add_check(
            checks,
            "每页都带 page_type、core_role、design_elements、conversion_goal",
            fields_ok,
            "已检查 page_breakdown 字段结构",
        )
        _add_check(
            checks,
            "图文报告包含 structure_summary 和 design_pattern",
            _has_nonempty_text(structure_summary, "description") and _has_nonempty_text(design_pattern, "description"),
            f"structure_summary keys={sorted(structure_summary.keys())}, design_pattern keys={sorted(design_pattern.keys())}",
        )
        has_visual_assets = bool(asset_index.get("page_images")) or bool(asset_index.get("contact_sheet"))
        _add_check(
            checks,
            "图文报告保留页卡素材索引",
            has_visual_assets,
            f"page_images={len(asset_index.get('page_images', [])) if isinstance(asset_index.get('page_images'), list) else 0}, contact_sheet={len(asset_index.get('contact_sheet', [])) if isinstance(asset_index.get('contact_sheet'), list) else 0}",
        )

    passed = sum(1 for item in checks if item["passed"])
    total = len(checks)
    summary = {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "pass_rate": round((passed / total), 2) if total else 0.0,
    }
    result = {"expectations": checks, "summary": summary}

    if args.result_file:
        result_path = Path(args.result_file).expanduser().resolve()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
