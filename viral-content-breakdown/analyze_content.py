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
    parser.add_argument("--markdown-output", help="可选：同步输出 Markdown 报告路径")
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


def _page_sequence_name(page_types: List[str]) -> str:
    mapping = {
        "cover": "封面钩子",
        "intro": "痛点引入",
        "explanation": "概念解释",
        "scenario": "场景展开",
        "method": "起步动作",
        "evidence": "证据托底",
        "risk": "风险边界",
        "cta": "评论收藏收束",
        "unknown": "补充页",
    }
    readable = [mapping.get(item, item) for item in page_types if item in mapping]
    if not readable:
        return "静态图文链路未识别"
    return " -> ".join(readable[:8])


def _top_design_elements(page_breakdown: List[Dict[str, Any]]) -> List[str]:
    counts: Dict[str, int] = {}
    for item in page_breakdown:
        if not item.get("is_valid"):
            continue
        for elem in item.get("design_elements", []):
            counts[elem] = counts.get(elem, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ordered[:6]]


def _merge_text(*parts: Any) -> str:
    merged = " ".join(str(part).strip() for part in parts if str(part).strip())
    return re.sub(r"\s+", " ", merged).strip()


def _contains_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _method_item(method: str, confidence: float, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"method": method, "confidence": round(confidence, 2), "evidence": _normalize_evidence(evidence)}


def _idea_item(idea: str, rationale: str) -> Dict[str, Any]:
    return {"idea": idea, "rationale": rationale}


def _dedupe_methods(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        method = str(item.get("method", "")).strip()
        if not method or method in seen:
            continue
        seen.add(method)
        deduped.append(item)
    return deduped[:3]


def _dedupe_ideas(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        idea = str(item.get("idea", "")).strip()
        if not idea or idea in seen:
            continue
        seen.add(idea)
        deduped.append(item)
    return deduped


def _build_video_narrative_pattern(source_text: str, evidence_pool: List[Dict[str, Any]]) -> Dict[str, Any]:
    has_steps = _contains_any(source_text, [r"步骤|怎么做|第一|第二|第三|先.*再", r"\b1\b|\b2\b|\b3\b"])
    has_contrast = _contains_any(source_text, [r"不是.*而是", r"别再", r"你以为", r"其实", r"反而"])
    has_cta = _contains_any(source_text, [r"评论|收藏|关注|转发|下篇|想看"])
    has_case = _contains_any(source_text, [r"案例|比如|场景|客户|工作流|实测"])

    if has_contrast and has_steps:
        name = "反常识开场 -> 拆步骤 -> 行动收束"
        description = "先用反直觉判断抓停留，再用步骤化讲解承接理解，最后收束到评论/收藏动作。"
    elif has_case and has_steps:
        name = "场景切入 -> 方法拆解 -> 结果收束"
        description = "先把问题放进具体场景，再拆成可执行动作，最后回到结果或收益。"
    elif has_steps:
        name = "结果/痛点 -> 步骤清单 -> 行动召唤"
        description = "先给结果或痛点，再用清单式步骤降低理解成本，最后提示下一步动作。"
    elif has_cta:
        name = "信息抛出 -> 解释补充 -> 互动收束"
        description = "内容先给结论，再补关键解释，结尾明确把用户推向评论、收藏或追更。"
    else:
        name = "问题-方法-结果"
        description = "先抛出痛点/结果，再给方法，最后收束到收益或行动。"

    return {"name": name, "description": description, "evidence": evidence_pool[:3]}


def _build_video_production_methods(
    source_text: str,
    evidence_pool: List[Dict[str, Any]],
    visual_specs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    ratio = str(visual_specs.get("video_main_aspect_ratio", {}).get("value", "unknown"))
    has_screen = _contains_any(source_text, [r"截图|界面|浏览器|终端|页面|仪表盘|官网|插件"])
    has_steps = _contains_any(source_text, [r"步骤|第一|第二|第三|怎么做|设置|生成|保存"])
    has_voice = _contains_any(source_text, [r"我来|你可以|今天|我们|先看|先说"])
    methods: List[Dict[str, Any]] = []

    if has_screen:
        methods.append(_method_item("录屏/截图演示 + 后期字幕剪辑（推断）", 0.5, evidence_pool[:2]))
    if has_steps:
        methods.append(_method_item("剪映/CapCut 字幕模板 + 清单式讲解（推断）", 0.4, evidence_pool[1:3]))
    if has_voice or ratio == "9:16":
        methods.append(_method_item("真人口播 + 竖版移动端剪辑（推断）", 0.32, evidence_pool[2:4]))

    methods.extend(
        [
            _method_item("平台原生模板或基础 NLE 后期（推断）", 0.24, evidence_pool[3:5]),
            _method_item("PR/CapCut 一类通用剪辑软件（推断）", 0.18, evidence_pool[4:6]),
        ]
    )
    return _dedupe_methods(methods)


def _build_video_virality_drivers(
    hook_text: str,
    source_text: str,
    evidence_pool: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    drivers: List[Dict[str, Any]] = []
    has_contrast = _contains_any(hook_text + " " + source_text, [r"不是.*而是", r"你以为", r"其实", r"反而", r"别再"])
    has_steps = _contains_any(source_text, [r"步骤|第一|第二|第三|清单|怎么做"])
    has_case = _contains_any(source_text, [r"案例|比如|场景|工作流|客户|实测"])
    has_cta = _contains_any(source_text, [r"评论|收藏|关注|下篇|想看|转发"])

    if has_contrast:
        drivers.append(
            {
                "driver": "开场先给反常识或结果判断，能更快抓停留",
                "why": "用户在首屏就感知到信息差，更愿意继续看主体内容。",
                "evidence": evidence_pool[:2],
            }
        )
    elif hook_text:
        drivers.append(
            {
                "driver": "开场信息密度高，前一句就交代主题或收益",
                "why": "能降低前几秒流失，让用户更快判断这条内容值不值得继续看。",
                "evidence": evidence_pool[:2],
            }
        )

    if has_steps:
        drivers.append(
            {
                "driver": "主体按步骤或清单展开，降低理解成本",
                "why": "拆成步骤后，用户更容易收藏，也更容易把抽象方法转成动作。",
                "evidence": evidence_pool[1:4],
            }
        )
    elif has_case:
        drivers.append(
            {
                "driver": "中段放进具体场景或案例，抽象观点更容易被接受",
                "why": "场景化内容会让用户更容易代入，从而提升完播和转发意愿。",
                "evidence": evidence_pool[1:4],
            }
        )

    if has_cta:
        drivers.append(
            {
                "driver": "结尾有明确互动动作，能把观看转成评论或收藏",
                "why": "清晰 CTA 会把用户从被动观看推向主动互动，放大推荐信号。",
                "evidence": evidence_pool[3:6],
            }
        )
    else:
        drivers.append(
            {
                "driver": "结构从开场到收束比较完整，用户不容易中途掉线",
                "why": "即使没有强 CTA，完整的叙事闭环也会提升观看完成度。",
                "evidence": evidence_pool[2:5],
            }
        )
    return drivers[:3]


def _build_video_adaptation_ideas(source_text: str) -> List[Dict[str, Any]]:
    ideas: List[Dict[str, Any]] = []
    has_contrast = _contains_any(source_text, [r"不是.*而是", r"你以为", r"其实", r"反而", r"别再"])
    has_steps = _contains_any(source_text, [r"步骤|第一|第二|第三|清单|怎么做"])
    has_case = _contains_any(source_text, [r"案例|比如|场景|工作流|客户|实测"])
    has_cta = _contains_any(source_text, [r"评论|收藏|关注|下篇|想看|转发"])

    if has_contrast:
        ideas.append(
            _idea_item(
                "保留“反常识/纠偏”式开头，但把判断换成你自己领域里的真实误区。",
                "这样能延续高停留结构，同时避免跟原内容表达过于相似。",
            )
        )
    if has_steps:
        ideas.append(
            _idea_item(
                "主体继续做成 3 步或清单结构，每一步只讲一个可执行动作。",
                "步骤化结构最容易带来收藏，因为用户能直接照着做。",
            )
        )
    if has_case:
        ideas.append(
            _idea_item(
                "中段加一个你自己的真实场景或案例，不要只讲抽象观点。",
                "案例会显著增强可信度，也更容易让用户判断“这件事和我有关”。",
            )
        )
    if has_cta:
        ideas.append(
            _idea_item(
                "结尾继续保留评论型 CTA，但把问题换成更贴近你业务的追问。",
                "好的结尾问题能把点赞转成评论，提升后续分发。",
            )
        )

    ideas.extend(
        [
            _idea_item(
                "封面和第一句尽量提前交代受众或收益，不要让用户自己猜主题。",
                "越早说清“这条内容帮谁解决什么”，越容易保住首屏停留。",
            ),
            _idea_item(
                "如果内容偏复杂，就在中段加入一个结果对照或前后变化的微证据。",
                "对照能帮用户更快理解方法为什么值得学，而不是只听结论。",
            ),
        ]
    )
    return _dedupe_ideas(ideas)[:3]


def _build_image_post_methods(
    design_elements: List[str],
    page_types: List[str],
    evidence_pool: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    methods: List[Dict[str, Any]] = []
    joined = " ".join(design_elements)
    if "截图+文字混排" in joined:
        methods.append(_method_item("截图拼贴 + 静态排版工具（推断）", 0.5, evidence_pool[:2]))
    if "步骤编号" in joined or "method" in page_types:
        methods.append(_method_item("Canva/Figma 模板化长图排版（推断）", 0.4, evidence_pool[1:3]))
    if "概念示意图" in joined:
        methods.append(_method_item("示意图/AI 配图 + 后期排字（推断）", 0.28, evidence_pool[2:4]))
    methods.extend(
        [
            _method_item("真实截图 + 文字卡混排（推断）", 0.24, evidence_pool[2:4]),
            _method_item("移动端修图或平台内置制图工具（推断）", 0.18, evidence_pool[3:5]),
        ]
    )
    return _dedupe_methods(methods)


def _build_image_post_ideas(page_types: List[str], design_elements: List[str]) -> List[Dict[str, Any]]:
    ideas: List[Dict[str, Any]] = []
    joined = " ".join(design_elements)
    if "cover" in page_types:
        ideas.append(
            _idea_item(
                "封面页继续保留“主题 + 人群/结果”直给结构，不要把关键信息藏到第 2 页以后。",
                "图文首屏更依赖封面预期一致，封面弱了后面内容通常没有机会被看到。",
            )
        )
    if any(page_type in {"scenario", "method"} for page_type in page_types):
        ideas.append(
            _idea_item(
                "中段保留场景页或步骤页，每页只承担一个信息点。",
                "单页单信息点更容易被快速扫读，也更容易形成收藏价值。",
            )
        )
    if any(page_type in {"risk", "cta"} for page_type in page_types):
        ideas.append(
            _idea_item(
                "尾段保留风险边界或评论型 CTA，不要突然结束。",
                "图文尾页是把阅读转成互动的关键位置，少了这一页，链路会断。",
            )
        )
    if "截图+文字混排" in joined:
        ideas.append(
            _idea_item(
                "如果中段用了截图，就继续配一句解释性标题，而不是只堆界面画面。",
                "截图本身不一定会说话，最好让用户一眼知道这张图为什么重要。",
            )
        )
    ideas.extend(
        [
            _idea_item(
                "整篇改编时只复用页型节奏和信息顺序，不复写原文表达。",
                "这样既能保留成熟结构，又能避免内容同质化。",
            ),
            _idea_item(
                "设计上优先重复 2 到 3 个固定元素，比如编号、对比、截图框，而不是每页都换风格。",
                "固定元素会让整篇图文更像一个完整系列，阅读负担也更低。",
            ),
        ]
    )
    return _dedupe_ideas(ideas)[:3]


def _image_post_report(signals: Dict[str, Any]) -> Dict[str, Any]:
    meta = signals.get("meta", {})
    asset_index = signals.get("asset_index", {})
    post_content = signals.get("post_content", {})
    engagement_metrics = signals.get("engagement_metrics", {})
    visual_specs = signals.get("visual_specs", {})
    sig = signals.get("signals", {})

    page_breakdown = sig.get("page_analysis", []) if isinstance(sig.get("page_analysis", []), list) else []
    valid_pages = [item for item in page_breakdown if isinstance(item, dict) and item.get("is_valid")]
    blank_or_shell_frames = signals.get("blank_or_shell_frames", [])
    evidence_pool = _normalize_evidence(sig.get("evidence_pool", []))
    page_types = [str(item.get("page_type", "unknown")) for item in valid_pages]
    design_elements = _top_design_elements(page_breakdown)

    hook_text = ""
    if valid_pages:
        hook_text = str(valid_pages[0].get("summary", ""))[:120]
    if not hook_text:
        hook_text = str(post_content.get("title", "") or "图文开场信息不足，需补充人工判断")[:120]

    cover_title_text = ""
    if asset_index.get("cover_text"):
        cover_title_text = str(asset_index.get("cover_text", [""])[0])[:80]
    elif valid_pages:
        cover_title_text = str(valid_pages[0].get("summary", ""))[:80]

    structure_name = _page_sequence_name(page_types)
    structure_desc = (
        f"这是一篇按“{structure_name}”推进的图文笔记。"
        "前段先降低理解门槛，中段用场景或方法拉收藏，尾段用风险或 CTA 拉评论和追更。"
    )
    if not valid_pages:
        structure_desc = "未识别出足够的有效页卡，只能基于标题和正文做弱结构判断。"

    dominant_design = " + ".join(design_elements[:3]) if design_elements else "白底长文 + 少量示意图"
    design_desc = (
        "整体设计语言偏小红书教程型长图文："
        f"{dominant_design}。重心不在复杂设计，而在单页只讲一个信息点。"
    )

    virality_drivers: List[Dict[str, Any]] = []
    if any(item == "cover" for item in page_types):
        virality_drivers.append(
            {
                "driver": "封面页先交代主题和受众，点击后不需要二次理解",
                "why": "小红书图文更依赖封面预期一致，减少首屏流失。",
                "evidence": _normalize_evidence(valid_pages[:1][0].get("evidence", []) if valid_pages else evidence_pool[:1]),
            }
        )
    if any(item in {"scenario", "method"} for item in page_types):
        virality_drivers.append(
            {
                "driver": "中段用场景页和方法页提供具体价值，承接收藏需求",
                "why": "这类页卡直接回答“我能怎么用”，比纯观点更容易被保存。",
                "evidence": _normalize_evidence(
                    [ev for page in valid_pages for ev in page.get("evidence", []) if page.get("page_type") in {"scenario", "method"}][:3]
                ),
            }
        )
    if any(item in {"risk", "cta"} for item in page_types):
        virality_drivers.append(
            {
                "driver": "尾段补风险边界或下一篇钩子，推动评论和追更",
                "why": "小红书图文评论往往来自异议处理和下一步行动提示。",
                "evidence": _normalize_evidence(
                    [ev for page in valid_pages for ev in page.get("evidence", []) if page.get("page_type") in {"risk", "cta"}][:3]
                ),
            }
        )
    if not virality_drivers:
        virality_drivers = [
            {
                "driver": "图文结构完整，具备基础浏览链路",
                "why": "即使缺少强证据页，分段明确仍能降低阅读成本。",
                "evidence": evidence_pool[:2],
            }
        ]

    report = {
        "meta": {
            "url": meta.get("url", ""),
            "platform": meta.get("platform", "unknown"),
            "content_type": "image_post",
            "fetched_at": meta.get("fetched_at", utc_now_iso()),
            "published_at": meta.get("published_at", ""),
            "analyzed_at": utc_now_iso(),
            "language": "zh-CN",
        },
        "asset_index": {
            "video": asset_index.get("video", []),
            "images": asset_index.get("images", []),
            "page_images": asset_index.get("page_images", []),
            "contact_sheet": asset_index.get("contact_sheet", []),
            "audio": asset_index.get("audio", []),
            "transcript": asset_index.get("transcript", []),
            "cover_text": asset_index.get("cover_text", []),
        },
        "engagement_metrics": {
            "likes": engagement_metrics.get("likes"),
            "comments": engagement_metrics.get("comments"),
            "plays": engagement_metrics.get("plays"),
        },
        "visual_specs": {
            "video_main_aspect_ratio": visual_specs.get("video_main_aspect_ratio", {"value": "unknown"}),
            "subtitle_style_inference": visual_specs.get(
                "subtitle_style_inference",
                {"subtitle_size": "unknown", "font_style": "unknown", "confidence": 0.2, "reason": "无足够信息"},
            ),
        },
        "post_content": {
            "title": str(post_content.get("title", "")),
            "body": str(post_content.get("body", "")),
            "tags": post_content.get("tags", []) if isinstance(post_content.get("tags", []), list) else [],
        },
        "hook": {"text": hook_text, "evidence": _normalize_evidence(valid_pages[:1][0].get("evidence", []) if valid_pages else evidence_pool[:2])},
        "script_structure": [
            {
                "section": f"第{item.get('page')}页/{item.get('page_type', 'unknown')}",
                "text": str(item.get("summary", "")),
                "evidence": _normalize_evidence(item.get("evidence", [])),
            }
            for item in valid_pages
        ],
        "narrative_pattern": {
            "name": "图文页卡递进",
            "description": "单页单信息点，按封面/引入/解释/场景/方法/收束推进。",
            "evidence": _normalize_evidence(
                [ev for item in valid_pages[:3] for ev in item.get("evidence", [])][:4] or evidence_pool[:2]
            ),
        },
        "cover_title": {"text": cover_title_text or "none（未提取到明确封面字）", "evidence": evidence_pool[:2]},
        "voiceover_copy": {
            "text": str(post_content.get("body", "") or "none（图文内容，无独立口播稿）")[:500],
            "evidence": evidence_pool[:4],
        },
        "production_method_inference": _build_image_post_methods(design_elements, page_types, evidence_pool),
        "virality_drivers": virality_drivers[:3],
        "adaptation_ideas": _build_image_post_ideas(page_types, design_elements),
        "page_breakdown": page_breakdown,
        "structure_summary": {
            "name": structure_name,
            "description": structure_desc,
            "evidence": _normalize_evidence([ev for item in valid_pages[:4] for ev in item.get("evidence", [])][:5] or evidence_pool[:3]),
        },
        "design_pattern": {
            "name": "小红书教程型长图文",
            "description": design_desc,
            "elements": design_elements,
            "evidence": _normalize_evidence([ev for item in valid_pages[:4] for ev in item.get("evidence", [])][:5] or evidence_pool[:3]),
        },
        "blank_or_shell_frames": blank_or_shell_frames if isinstance(blank_or_shell_frames, list) else [],
        "limitations": signals.get("limitations", []) + ["图文页型判断基于 OCR + 视觉规则，仍需人工复核。"],
        "confidence_overall": 0.76 if valid_pages else 0.58,
    }
    return report


def _fallback_report(signals: Dict[str, Any]) -> Dict[str, Any]:
    if signals.get("meta", {}).get("content_type") == "image_post":
        return _image_post_report(signals)

    meta = signals.get("meta", {})
    asset_index = signals.get("asset_index", {})
    post_content = signals.get("post_content", {})
    engagement_metrics = signals.get("engagement_metrics", {})
    visual_specs = signals.get("visual_specs", {})
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

    source_text = _merge_text(
        post_content.get("title", ""),
        post_content.get("body", ""),
        combined_text,
        " ".join(hit.get("text", "") for hit in ocr_hits[:5]),
    )

    cover_title_text = ""
    if asset_index.get("cover_text"):
        cover_title_text = asset_index["cover_text"][0]
    elif ocr_hits:
        cover_title_text = str(ocr_hits[0].get("text", "")).splitlines()[0][:80]

    voiceover = combined_text[:500] if combined_text else "none（未提取到可用口播文本）"
    narrative_pattern = _build_video_narrative_pattern(source_text, evidence_pool)
    production_methods = _build_video_production_methods(source_text, evidence_pool, visual_specs)
    virality_drivers = _build_video_virality_drivers(hook_text, source_text, evidence_pool)
    adaptation_ideas = _build_video_adaptation_ideas(source_text)

    report = {
        "meta": {
            "url": meta.get("url", ""),
            "platform": meta.get("platform", "unknown"),
            "content_type": meta.get("content_type", "unknown"),
            "fetched_at": meta.get("fetched_at", utc_now_iso()),
            "published_at": meta.get("published_at", ""),
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
        "engagement_metrics": {
            "likes": engagement_metrics.get("likes"),
            "comments": engagement_metrics.get("comments"),
            "plays": engagement_metrics.get("plays"),
        },
        "visual_specs": {
            "video_main_aspect_ratio": visual_specs.get("video_main_aspect_ratio", {"value": "unknown"}),
            "subtitle_style_inference": visual_specs.get(
                "subtitle_style_inference",
                {"subtitle_size": "unknown", "font_style": "unknown", "confidence": 0.2, "reason": "无足够信息"},
            ),
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
        "narrative_pattern": narrative_pattern,
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
        "adaptation_ideas": adaptation_ideas,
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
        "字段必须包含：meta,asset_index,engagement_metrics,visual_specs,post_content,hook,script_structure,narrative_pattern,cover_title,"
        "voiceover_copy,production_method_inference,virality_drivers,adaptation_ideas,limitations,confidence_overall。"
        "要求：结论附 evidence；production_method_inference 必须是 Top3 推断并给 confidence；"
        "adaptation_ideas 只给思路，不给完整改写稿；语言为简体中文。"
    )

    content = {
        "meta": signals.get("meta", {}),
        "asset_index": signals.get("asset_index", {}),
        "engagement_metrics": signals.get("engagement_metrics", {}),
        "visual_specs": signals.get("visual_specs", {}),
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
    for key in required:
        if key not in report:
            report[key] = (
                {}
                if key
                in {
                    "meta",
                    "asset_index",
                    "engagement_metrics",
                    "visual_specs",
                    "post_content",
                    "hook",
                    "narrative_pattern",
                    "cover_title",
                    "voiceover_copy",
                    "structure_summary",
                    "design_pattern",
                }
                else []
            )

    for key in [
        "meta",
        "asset_index",
        "engagement_metrics",
        "visual_specs",
        "post_content",
        "hook",
        "narrative_pattern",
        "cover_title",
        "voiceover_copy",
        "structure_summary",
        "design_pattern",
    ]:
        if not isinstance(report.get(key), dict):
            report[key] = {}
    for key in [
        "script_structure",
        "production_method_inference",
        "virality_drivers",
        "adaptation_ideas",
        "page_breakdown",
        "blank_or_shell_frames",
        "limitations",
    ]:
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

    if isinstance(report.get("structure_summary"), dict):
        report["structure_summary"]["evidence"] = _normalize_evidence(
            report["structure_summary"].get("evidence", _empty_evidence())
        )

    if isinstance(report.get("design_pattern"), dict):
        report["design_pattern"]["evidence"] = _normalize_evidence(
            report["design_pattern"].get("evidence", _empty_evidence())
        )
        if not isinstance(report["design_pattern"].get("elements"), list):
            report["design_pattern"]["elements"] = []

    if isinstance(report.get("page_breakdown"), list):
        normalized_pages: List[Dict[str, Any]] = []
        for item in report["page_breakdown"]:
            if not isinstance(item, dict):
                continue
            normalized_pages.append(
                {
                    "page": int(item.get("page", len(normalized_pages) + 1) or len(normalized_pages) + 1),
                    "source": str(item.get("source", "")),
                    "page_type": str(item.get("page_type", "unknown")),
                    "is_valid": bool(item.get("is_valid", True)),
                    "summary": str(item.get("summary", "")),
                    "core_role": str(item.get("core_role", "")),
                    "design_elements": item.get("design_elements", [])
                    if isinstance(item.get("design_elements", []), list)
                    else [],
                    "conversion_goal": str(item.get("conversion_goal", "")),
                    "evidence": _normalize_evidence(item.get("evidence", _empty_evidence())),
                }
            )
        report["page_breakdown"] = normalized_pages

    # meta/asset_index 兜底
    report["meta"] = {
        "url": report.get("meta", {}).get("url") or signals.get("meta", {}).get("url", ""),
        "platform": report.get("meta", {}).get("platform") or signals.get("meta", {}).get("platform", "unknown"),
        "content_type": report.get("meta", {}).get("content_type") or signals.get("meta", {}).get("content_type", "unknown"),
        "fetched_at": report.get("meta", {}).get("fetched_at") or signals.get("meta", {}).get("fetched_at", utc_now_iso()),
        "published_at": report.get("meta", {}).get("published_at") or signals.get("meta", {}).get("published_at", ""),
        "analyzed_at": utc_now_iso(),
        "language": "zh-CN",
    }

    report["asset_index"] = {
        "video": signals.get("asset_index", {}).get("video", []),
        "images": signals.get("asset_index", {}).get("images", []),
        "page_images": signals.get("asset_index", {}).get("page_images", []),
        "contact_sheet": signals.get("asset_index", {}).get("contact_sheet", []),
        "audio": signals.get("asset_index", {}).get("audio", []),
        "transcript": signals.get("asset_index", {}).get("transcript", []),
        "cover_text": signals.get("asset_index", {}).get("cover_text", []),
    }
    report["engagement_metrics"] = {
        "likes": signals.get("engagement_metrics", {}).get("likes"),
        "comments": signals.get("engagement_metrics", {}).get("comments"),
        "plays": signals.get("engagement_metrics", {}).get("plays"),
    }
    report["visual_specs"] = {
        "video_main_aspect_ratio": signals.get("visual_specs", {}).get("video_main_aspect_ratio", {"value": "unknown"}),
        "subtitle_style_inference": signals.get("visual_specs", {}).get(
            "subtitle_style_inference",
            {"subtitle_size": "unknown", "font_style": "unknown", "confidence": 0.2, "reason": "无足够信息"},
        ),
    }
    report["post_content"] = {
        "title": str(signals.get("post_content", {}).get("title", "")),
        "body": str(signals.get("post_content", {}).get("body", "")),
        "tags": signals.get("post_content", {}).get("tags", [])
        if isinstance(signals.get("post_content", {}).get("tags", []), list)
        else [],
    }
    if not report.get("blank_or_shell_frames"):
        report["blank_or_shell_frames"] = signals.get("blank_or_shell_frames", [])

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


def _fmt_num(value: Any) -> str:
    if value is None or value == "":
        return "未知"
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def _render_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("meta", {})
    post = report.get("post_content", {})
    hook = report.get("hook", {})
    cover = report.get("cover_title", {})
    voice = report.get("voiceover_copy", {})
    metrics = report.get("engagement_metrics", {})
    visual = report.get("visual_specs", {})
    ratio = visual.get("video_main_aspect_ratio", {})
    subtitle = visual.get("subtitle_style_inference", {})
    tags = post.get("tags", []) if isinstance(post.get("tags", []), list) else []
    script = report.get("script_structure", []) if isinstance(report.get("script_structure"), list) else []
    drivers = report.get("virality_drivers", []) if isinstance(report.get("virality_drivers"), list) else []
    methods = report.get("production_method_inference", []) if isinstance(report.get("production_method_inference"), list) else []
    ideas = report.get("adaptation_ideas", []) if isinstance(report.get("adaptation_ideas"), list) else []
    page_breakdown = report.get("page_breakdown", []) if isinstance(report.get("page_breakdown"), list) else []
    structure_summary = report.get("structure_summary", {}) if isinstance(report.get("structure_summary"), dict) else {}
    design_pattern = report.get("design_pattern", {}) if isinstance(report.get("design_pattern"), dict) else {}
    blank_or_shell_frames = report.get("blank_or_shell_frames", []) if isinstance(report.get("blank_or_shell_frames"), list) else []
    limitations = report.get("limitations", []) if isinstance(report.get("limitations"), list) else []

    lines: List[str] = []
    lines.append("# 爆款内容拆解报告")
    lines.append("")
    lines.append("## 基本信息")
    lines.append(f"- 链接：{meta.get('url', '')}")
    lines.append(f"- 平台：{meta.get('platform', 'unknown')}")
    lines.append(f"- 内容类型：{meta.get('content_type', 'unknown')}")
    lines.append(f"- 抓取时间：{meta.get('fetched_at', '')}")
    lines.append(f"- 发布时间：{meta.get('published_at', '') or '未知'}")
    lines.append(f"- 分析模式：{meta.get('analysis_mode', 'fallback')}")
    lines.append("")
    if meta.get("content_type") == "image_post":
        contact_sheet = report.get("asset_index", {}).get("contact_sheet", [])
        lines.append("## 图文素材")
        lines.append(f"- 页卡数：{len(report.get('asset_index', {}).get('page_images', []) or [])}")
        lines.append(f"- Contact sheet：{contact_sheet[0] if contact_sheet else '无'}")
        lines.append("")
    lines.append("## 热度数据")
    lines.append(f"- 点赞：{_fmt_num(metrics.get('likes'))}")
    lines.append(f"- 评论：{_fmt_num(metrics.get('comments'))}")
    lines.append(f"- 播放：{_fmt_num(metrics.get('plays'))}")
    lines.append("")
    lines.append("## 标题与正文")
    lines.append(f"- 标题：{post.get('title', '') or '无'}")
    lines.append(f"- 封面标题：{cover.get('text', '') or '无'}")
    lines.append(f"- Tag：{' / '.join([str(t) for t in tags]) if tags else '无'}")
    lines.append(f"- 正文：{(post.get('body', '') or '无')[:1200]}")
    lines.append("")
    lines.append("## 视频画面参数")
    lines.append(
        f"- 主画面宽高比：{ratio.get('value', 'unknown')} "
        f"(宽={ratio.get('width', '未知')}, 高={ratio.get('height', '未知')}, 置信={ratio.get('confidence', '未知')})"
    )
    lines.append(
        f"- 字幕大小：{subtitle.get('subtitle_size', 'unknown')} "
        f"(置信={subtitle.get('confidence', '未知')})"
    )
    lines.append(f"- 字体格式：{subtitle.get('font_style', 'unknown')}")
    lines.append(f"- 判断依据：{subtitle.get('reason', '无')}")
    lines.append("")
    if meta.get("content_type") == "image_post":
        lines.append("## 图文链路拆解")
        lines.append(f"- 开场钩子：{hook.get('text', '') or '无'}")
        lines.append(f"- 结构总结：{structure_summary.get('name', '未知')}")
        lines.append(f"- 结构说明：{structure_summary.get('description', '无')}")
        lines.append(f"- 设计模式：{design_pattern.get('name', '未知')}")
        lines.append(f"- 设计说明：{design_pattern.get('description', '无')}")
        design_elems = design_pattern.get("elements", [])
        lines.append(f"- 关键设计元素：{' / '.join([str(x) for x in design_elems]) if design_elems else '无'}")
        lines.append("")
        lines.append("### 逐页分析")
        if page_breakdown:
            for item in page_breakdown:
                lines.append(
                    f"{item.get('page', '?')}. [{item.get('page_type', 'unknown')}] {item.get('core_role', '')}: {item.get('summary', '')}"
                )
                elems = item.get("design_elements", [])
                if elems:
                    lines.append(f"   - 设计元素：{' / '.join([str(x) for x in elems])}")
                if item.get("conversion_goal"):
                    lines.append(f"   - 转化作用：{item.get('conversion_goal')}")
        else:
            lines.append("- 无可用逐页分析。")
        lines.append("")
        lines.append("### 无效帧")
        if blank_or_shell_frames:
            for item in blank_or_shell_frames:
                lines.append(f"- 第 {item.get('page', '?')} 页：{item.get('reason', '无效页')}")
        else:
            lines.append("- 无。")
        lines.append("")
    else:
        lines.append("## 视频口播级拆解")
        lines.append(f"- 开场钩子：{hook.get('text', '') or '无'}")
        lines.append(f"- 口播稿提炼：{voice.get('text', '') or 'none'}")
        lines.append("")
        lines.append("### 分段脚本")
        if script:
            for idx, sec in enumerate(script, start=1):
                lines.append(f"{idx}. {sec.get('section', '未命名')}: {sec.get('text', '')}")
        else:
            lines.append("- 无可用分段。")
        lines.append("")
    lines.append("## 叙事与爆点")
    narrative = report.get("narrative_pattern", {})
    lines.append(f"- 叙事方式：{narrative.get('name', '未知')}")
    lines.append(f"- 说明：{narrative.get('description', '无')}")
    if drivers:
        lines.append("")
        lines.append("### 爆点驱动")
        for idx, d in enumerate(drivers, start=1):
            lines.append(f"{idx}. {d.get('driver', '未命名')}: {d.get('why', '')}")
    lines.append("")
    lines.append("## 制作方式推断（Top3）")
    if methods:
        for idx, m in enumerate(methods, start=1):
            lines.append(f"{idx}. {m.get('method', '未知')}（置信 {m.get('confidence', 0)}）")
    else:
        lines.append("- 无可用推断。")
    lines.append("")
    lines.append("## 可复制拍法与优化建议")
    if ideas:
        for idx, idea in enumerate(ideas, start=1):
            lines.append(f"{idx}. {idea.get('idea', '未命名')}")
            lines.append(f"   - 理由：{idea.get('rationale', '')}")
    else:
        lines.append("- 无可用建议。")
    lines.append("")
    lines.append("## 限制说明")
    if limitations:
        for item in limitations:
            lines.append(f"- {item}")
    else:
        lines.append("- 无。")
    return "\n".join(lines).strip() + "\n"


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
    content_type = signals.get("meta", {}).get("content_type", "unknown")

    if content_type == "image_post":
        report = _fallback_report(signals)
    elif os.getenv("OPENAI_API_KEY"):
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
    if args.markdown_output:
        md_path = Path(args.markdown_output).resolve()
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
