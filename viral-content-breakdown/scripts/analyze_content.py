#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from common import read_json, structured_error, utc_now_iso, write_json

ALLOWED_EVIDENCE_TYPES = {
    "timestamp",
    "frame_ocr",
    "transcript_span",
    "cover_ocr",
    "visual_pattern",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于信号生成结构化爆款拆解 report.json")
    parser.add_argument("--signals", required=True, help="extract_signals.py 输出 JSON")
    parser.add_argument("--output", required=True, help="最终 report.json 路径")
    parser.add_argument("--model", default="gpt-4.1-mini")
    return parser.parse_args()


def _empty_evidence() -> List[Dict[str, Any]]:
    return []


def _normalize_evidence(items: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for item in items:
        if not isinstance(item, dict):
            continue
        etype = item.get("type")
        if etype not in ALLOWED_EVIDENCE_TYPES:
            etype = "transcript_span"
        normalized.append(
            {
                "type": etype,
                "source": str(item.get("source", ""))[:300],
                "locator": str(item.get("locator", ""))[:120],
                "snippet": str(item.get("snippet", ""))[:200],
                "confidence": float(item.get("confidence", 0.5) or 0.5),
            }
        )
    return normalized


def _chunk_text(chunks: List[Dict[str, Any]]) -> str:
    text = " ".join(c.get("text", "") for c in chunks if c.get("text"))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000]


def _fallback_report(signals: Dict[str, Any]) -> Dict[str, Any]:
    meta = signals.get("meta", {})
    asset_index = signals.get("asset_index", {})
    post_content = signals.get("post_content", {})
    sig = signals.get("signals", {})

    transcript_chunks = sig.get("transcript_chunks", [])
    ocr_hits = sig.get("ocr_hits", [])
    evidence_pool = _normalize_evidence(sig.get("evidence_pool", []))

    combined_text = _chunk_text(transcript_chunks)
    hook_text = ""
    if transcript_chunks:
        hook_text = transcript_chunks[0].get("text", "")[:120]
    elif ocr_hits:
        hook_text = str(ocr_hits[0].get("text", ""))[:120]
    if not hook_text:
        hook_text = "开场信息不足，需补充人工判断"

    script_sections: List[Dict[str, Any]] = []
    if transcript_chunks:
        section_size = max(1, len(transcript_chunks) // 3)
        section_names = ["开场钩子", "主体展开", "收束/行动召唤"]
        for i, name in enumerate(section_names):
            s = transcript_chunks[i * section_size : (i + 1) * section_size]
            txt = " ".join(x.get("text", "") for x in s).strip()[:280] or "内容不足"
            script_sections.append(
                {
                    "section": name,
                    "text": txt,
                    "evidence": _normalize_evidence(
                        [
                            {
                                "type": "transcript_span",
                                "source": s[0].get("source", "") if s else "",
                                "locator": f"line:{s[0].get('line', '')}" if s else "",
                                "snippet": txt,
                                "confidence": 0.7,
                            }
                        ]
                    ),
                }
            )
    else:
        script_sections = [
            {
                "section": "结构识别",
                "text": "缺少可用字幕/口播文本，无法完整切分脚本结构。",
                "evidence": evidence_pool[:1],
            }
        ]

    cover_title_text = ""
    if asset_index.get("cover_text"):
        cover_title_text = asset_index["cover_text"][0]
    elif ocr_hits:
        cover_title_text = str(ocr_hits[0].get("text", "")).splitlines()[0][:80]

    voiceover = combined_text[:500] if combined_text else "none（未提取到可用口播文本）"

    production_methods = [
        {
            "method": "剪映/CapCut（推断）",
            "confidence": 0.45,
            "evidence": evidence_pool[:2],
        },
        {
            "method": "平台内置模板（推断）",
            "confidence": 0.35,
            "evidence": evidence_pool[2:4],
        },
        {
            "method": "PR/专业剪辑软件（推断）",
            "confidence": 0.2,
            "evidence": evidence_pool[4:6],
        },
    ]

    virality_drivers = [
        {
            "driver": "开场钩子直接给结果或冲突",
            "why": "前 1-3 秒给出强信息密度，提高停留率",
            "evidence": evidence_pool[:2],
        },
        {
            "driver": "叙事节奏快，信息分段清晰",
            "why": "降低理解成本，推动完播",
            "evidence": evidence_pool[2:4],
        },
        {
            "driver": "主题与受众痛点高度贴合",
            "why": "触发评论与转发意愿",
            "evidence": evidence_pool[4:6],
        },
    ]

    report = {
        "meta": {
            "url": meta.get("url", ""),
            "platform": meta.get("platform", "unknown"),
            "content_type": meta.get("content_type", "unknown"),
            "fetched_at": meta.get("fetched_at", utc_now_iso()),
            "analyzed_at": utc_now_iso(),
            "language": "zh-CN",
        },
        "asset_index": {
            "video": asset_index.get("video", []),
            "images": asset_index.get("images", []),
            "audio": asset_index.get("audio", []),
            "transcript": asset_index.get("transcript", []),
            "cover_text": asset_index.get("cover_text", []),
        },
        "post_content": {
            "title": str(post_content.get("title", "")),
            "body": str(post_content.get("body", "")),
            "tags": post_content.get("tags", []) if isinstance(post_content.get("tags", []), list) else [],
        },
        "hook": {
            "text": hook_text,
            "evidence": evidence_pool[:3],
        },
        "script_structure": script_sections,
        "narrative_pattern": {
            "name": "问题-方法-结果",
            "description": "先抛出痛点/结果，再给方法，最后收束到收益或行动。",
            "evidence": evidence_pool[:3],
        },
        "cover_title": {
            "text": cover_title_text or "none（未提取到明确封面字）",
            "evidence": evidence_pool[:2],
        },
        "voiceover_copy": {
            "text": voiceover,
            "evidence": evidence_pool[:4],
        },
        "production_method_inference": production_methods,
        "virality_drivers": virality_drivers,
        "adaptation_ideas": [
            {
                "idea": "保留原内容的高密度开场，但改成你的真实案例切入。",
                "rationale": "减少同质化，同时延续高停留结构。",
            },
            {
                "idea": "将主体拆成 3 个可执行步骤，每步加一个可量化结果。",
                "rationale": "提高可操作感与收藏率。",
            },
            {
                "idea": "结尾增加反直觉观点或对照结论，引导评论区讨论。",
                "rationale": "提升互动率，放大推荐信号。",
            },
        ],
        "limitations": signals.get("limitations", []) + [
            "制作软件识别属于推断，非平台官方标注。",
        ],
        "confidence_overall": 0.68,
    }
    return report


def _llm_report(signals: Dict[str, Any], model: str) -> Dict[str, Any]:
    from openai import OpenAI  # type: ignore

    client = OpenAI()
    prompt = (
        "你是短视频/图文爆款拆解分析师。"
        "请严格输出 JSON 对象，不要输出任何额外文本。"
        "字段必须包含：meta,asset_index,post_content,hook,script_structure,narrative_pattern,cover_title,"
        "voiceover_copy,production_method_inference,virality_drivers,adaptation_ideas,limitations,confidence_overall。"
        "要求：结论附 evidence；production_method_inference 必须是 Top3 推断并给 confidence；"
        "adaptation_ideas 只给思路，不给完整改写稿；语言为简体中文。"
    )

    content = {
        "meta": signals.get("meta", {}),
        "asset_index": signals.get("asset_index", {}),
        "post_content": signals.get("post_content", {}),
        "signals": signals.get("signals", {}),
        "limitations": signals.get("limitations", []),
    }

    rsp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
        ],
        temperature=0.2,
    )
    raw = rsp.choices[0].message.content or "{}"
    return json.loads(raw)


def _validate_report(report: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    # 必填字段兜底
    required = [
        "meta",
        "asset_index",
        "post_content",
        "hook",
        "script_structure",
        "narrative_pattern",
        "cover_title",
        "voiceover_copy",
        "production_method_inference",
        "virality_drivers",
        "adaptation_ideas",
        "limitations",
        "confidence_overall",
    ]
    for key in required:
        if key not in report:
            report[key] = {} if key in {"meta", "asset_index", "post_content", "hook", "narrative_pattern", "cover_title", "voiceover_copy"} else []

    for key in ["meta", "asset_index", "post_content", "hook", "narrative_pattern", "cover_title", "voiceover_copy"]:
        if not isinstance(report.get(key), dict):
            report[key] = {}
    for key in ["script_structure", "production_method_inference", "virality_drivers", "adaptation_ideas", "limitations"]:
        if not isinstance(report.get(key), list):
            report[key] = []

    # evidence 规范化
    if isinstance(report.get("hook"), dict):
        report["hook"]["evidence"] = _normalize_evidence(report["hook"].get("evidence", _empty_evidence()))

    if isinstance(report.get("script_structure"), list):
        for item in report["script_structure"]:
            if isinstance(item, dict):
                item["evidence"] = _normalize_evidence(item.get("evidence", _empty_evidence()))

    if isinstance(report.get("narrative_pattern"), dict):
        report["narrative_pattern"]["evidence"] = _normalize_evidence(
            report["narrative_pattern"].get("evidence", _empty_evidence())
        )

    if isinstance(report.get("cover_title"), dict):
        report["cover_title"]["evidence"] = _normalize_evidence(report["cover_title"].get("evidence", _empty_evidence()))

    if isinstance(report.get("voiceover_copy"), dict):
        report["voiceover_copy"]["evidence"] = _normalize_evidence(
            report["voiceover_copy"].get("evidence", _empty_evidence())
        )

    if isinstance(report.get("production_method_inference"), list):
        report["production_method_inference"] = report["production_method_inference"][:3]
        for item in report["production_method_inference"]:
            if isinstance(item, dict):
                item["evidence"] = _normalize_evidence(item.get("evidence", _empty_evidence()))
                item["confidence"] = float(item.get("confidence", 0.33) or 0.33)

    if isinstance(report.get("virality_drivers"), list):
        for item in report["virality_drivers"]:
            if isinstance(item, dict):
                item["evidence"] = _normalize_evidence(item.get("evidence", _empty_evidence()))

    # meta/asset_index 兜底
    report["meta"] = {
        "url": report.get("meta", {}).get("url") or signals.get("meta", {}).get("url", ""),
        "platform": report.get("meta", {}).get("platform") or signals.get("meta", {}).get("platform", "unknown"),
        "content_type": report.get("meta", {}).get("content_type") or signals.get("meta", {}).get("content_type", "unknown"),
        "fetched_at": report.get("meta", {}).get("fetched_at") or signals.get("meta", {}).get("fetched_at", utc_now_iso()),
        "analyzed_at": utc_now_iso(),
        "language": "zh-CN",
    }

    report["asset_index"] = {
        "video": signals.get("asset_index", {}).get("video", []),
        "images": signals.get("asset_index", {}).get("images", []),
        "audio": signals.get("asset_index", {}).get("audio", []),
        "transcript": signals.get("asset_index", {}).get("transcript", []),
        "cover_text": signals.get("asset_index", {}).get("cover_text", []),
    }
    report["post_content"] = {
        "title": str(signals.get("post_content", {}).get("title", "")),
        "body": str(signals.get("post_content", {}).get("body", "")),
        "tags": signals.get("post_content", {}).get("tags", [])
        if isinstance(signals.get("post_content", {}).get("tags", []), list)
        else [],
    }

    try:
        report["confidence_overall"] = float(report.get("confidence_overall", 0.65))
    except Exception:
        report["confidence_overall"] = 0.65

    if not isinstance(report.get("limitations"), list):
        report["limitations"] = []

    # 保底：确保 hooks/drivers 含 evidence
    if not report.get("hook", {}).get("evidence"):
        report["hook"]["evidence"] = _normalize_evidence(signals.get("signals", {}).get("evidence_pool", [])[:2])

    if isinstance(report.get("virality_drivers"), list):
        for driver in report["virality_drivers"]:
            if isinstance(driver, dict) and not driver.get("evidence"):
                driver["evidence"] = _normalize_evidence(signals.get("signals", {}).get("evidence_pool", [])[:2])

    return report


def main() -> int:
    args = parse_args()
    signals = read_json(Path(args.signals).resolve(), default={})
    out_path = Path(args.output).resolve()

    if not signals.get("ok"):
        err = structured_error(
            "UPSTREAM_SIGNALS_FAILED",
            "signals 数据不可用，无法生成报告",
            "先修复 extract_signals.py 输出，再重试 analyze_content.py",
            {"upstream": signals.get("error")},
        )
        write_json(out_path, err)
        print(out_path)
        return 1

    report: Dict[str, Any]
    llm_used = False

    if os.getenv("OPENAI_API_KEY"):
        try:
            report = _llm_report(signals, args.model)
            llm_used = True
        except Exception:
            report = _fallback_report(signals)
    else:
        report = _fallback_report(signals)

    report = _validate_report(report, signals)
    report["meta"]["analysis_mode"] = "llm" if llm_used else "fallback"

    write_json(out_path, report)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
