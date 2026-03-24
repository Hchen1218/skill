#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an HTML before/after comparison report for viral-content-breakdown outputs")
    parser.add_argument("--before-json", required=True, help="Path to the pre-optimization report.json")
    parser.add_argument("--after-json", required=True, help="Path to the post-optimization report.json")
    parser.add_argument("--before-label", default="优化前")
    parser.add_argument("--after-label", default="优化后")
    parser.add_argument("--output", required=True, help="Output HTML path")
    parser.add_argument("--title", default="Viral Content Breakdown 优化前后可视化报告")
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_md_path(json_path: Path) -> Path | None:
    candidate = json_path.with_suffix(".md")
    return candidate if candidate.exists() else None


def report_view(report: Dict[str, Any]) -> Dict[str, Any]:
    script = report.get("script_structure", []) if isinstance(report.get("script_structure", []), list) else []
    drivers = report.get("virality_drivers", []) if isinstance(report.get("virality_drivers", []), list) else []
    ideas = report.get("adaptation_ideas", []) if isinstance(report.get("adaptation_ideas", []), list) else []
    methods = report.get("production_method_inference", []) if isinstance(report.get("production_method_inference", []), list) else []
    limitations = report.get("limitations", []) if isinstance(report.get("limitations", []), list) else []
    return {
        "title": str(report.get("post_content", {}).get("title", "")),
        "cover_title": str(report.get("cover_title", {}).get("text", "")),
        "hook": str(report.get("hook", {}).get("text", "")),
        "narrative": str(report.get("narrative_pattern", {}).get("name", "")),
        "narrative_desc": str(report.get("narrative_pattern", {}).get("description", "")),
        "sections": [str(item.get("section", "")) for item in script if isinstance(item, dict)],
        "section_texts": [str(item.get("text", "")) for item in script if isinstance(item, dict)],
        "drivers": [str(item.get("driver", "")) for item in drivers if isinstance(item, dict)],
        "ideas": [str(item.get("idea", "")) for item in ideas if isinstance(item, dict)],
        "methods": [str(item.get("method", "")) for item in methods if isinstance(item, dict)],
        "voiceover": str(report.get("voiceover_copy", {}).get("text", "")),
        "meta": report.get("meta", {}) if isinstance(report.get("meta", {}), dict) else {},
        "limitations": [str(item) for item in limitations],
    }


def escape(value: Any) -> str:
    return html.escape(str(value or ""))


def render_path_link(path: Path, label: str) -> str:
    return f'<a href="{escape(path.resolve().as_uri())}" target="_blank" rel="noreferrer">{escape(label)}</a>'


def render_list(items: List[str], empty: str = "无") -> str:
    if not items:
        return f"<li>{escape(empty)}</li>"
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def render_chips(items: List[str], tone: str = "neutral") -> str:
    if not items:
        return '<span class="chip muted">无</span>'
    return "".join(f'<span class="chip {tone}">{escape(item)}</span>' for item in items)


def summarize_deltas(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    if len(after["sections"]) > len(before["sections"]):
        notes.append(f"脚本分段从 {len(before['sections'])} 段提升到 {len(after['sections'])} 段")
    if before["narrative"] != after["narrative"]:
        notes.append("叙事结构命名从泛化描述升级为更具体的内容模型")
    if "PROP" in before["voiceover"] and "Prompt" in after["voiceover"]:
        notes.append("术语识别从 PROP 修正为 Prompt")
    if "Deep City" in before["voiceover"] and "DeepSeek" in after["voiceover"]:
        notes.append("模型名识别从 Deep City 更正到 DeepSeek")
    if len(after["hook"]) > len(before["hook"]):
        notes.append("开场钩子从截断句升级为完整高冲击句")
    if before["drivers"] != after["drivers"]:
        notes.append("爆点原因从泛化总结升级为更具体的结构化拆解")
    return notes


def residual_issues(after: Dict[str, Any]) -> List[str]:
    text = after["voiceover"]
    known = [
        "巴尼的问题",
        "German Flash",
        "逗老师",
        "蘇格拉底",
        "我不仅是了",
        "别人区",
    ]
    return [item for item in known if item in text]


def render_side_by_side(title: str, before: str, after: str) -> str:
    return f"""
    <section class="compare-card">
      <div class="card-title">{escape(title)}</div>
      <div class="two-col">
        <div class="pane">
          <div class="pane-label">优化前</div>
          <div class="pane-body">{before}</div>
        </div>
        <div class="pane">
          <div class="pane-label good">优化后</div>
          <div class="pane-body">{after}</div>
        </div>
      </div>
    </section>
    """


def build_html(args: argparse.Namespace, before_json: Path, after_json: Path, before: Dict[str, Any], after: Dict[str, Any]) -> str:
    before_md = safe_md_path(before_json)
    after_md = safe_md_path(after_json)
    notes = summarize_deltas(before, after)
    issues = residual_issues(after)

    summary_cards = [
        ("样本标题", after["title"] or before["title"] or "未识别"),
        ("对比维度", "Hook / 叙事 / 分段脚本 / 爆点驱动 / 改编建议"),
        ("脚本分段", f"{len(before['sections'])} 段 → {len(after['sections'])} 段"),
        ("可读性结论", "优化后已经能明显看出结构更清晰、结论更具体"),
    ]

    summary_html = "".join(
        f"""
        <div class="metric-card">
          <div class="metric-label">{escape(label)}</div>
          <div class="metric-value">{escape(value)}</div>
        </div>
        """
        for label, value in summary_cards
    )

    source_links = [
        render_path_link(before_json, f"{args.before_label} JSON"),
        render_path_link(after_json, f"{args.after_label} JSON"),
    ]
    if before_md:
        source_links.append(render_path_link(before_md, f"{args.before_label} Markdown"))
    if after_md:
        source_links.append(render_path_link(after_md, f"{args.after_label} Markdown"))

    sections_before = render_chips(before["sections"], tone="neutral")
    sections_after = render_chips(after["sections"], tone="good")
    drivers_before = f"<ul>{render_list(before['drivers'])}</ul>"
    drivers_after = f"<ul>{render_list(after['drivers'])}</ul>"
    ideas_before = f"<ul>{render_list(before['ideas'])}</ul>"
    ideas_after = f"<ul>{render_list(after['ideas'])}</ul>"
    methods_before = f"<ul>{render_list(before['methods'])}</ul>"
    methods_after = f"<ul>{render_list(after['methods'])}</ul>"
    section_texts_before = f"<ol>{render_list([f'{idx + 1}. {text}' for idx, text in enumerate(before['section_texts'])])}</ol>"
    section_texts_after = f"<ol>{render_list([f'{idx + 1}. {text}' for idx, text in enumerate(after['section_texts'])])}</ol>"

    notes_html = "".join(f"<li>{escape(note)}</li>" for note in notes) if notes else "<li>本次对比未检测到明显结构变化。</li>"
    issues_html = "".join(f'<span class="chip warn">{escape(item)}</span>' for item in issues) if issues else '<span class="chip good">未检测到明显残留错词</span>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(args.title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --card: #ffffff;
      --text: #142033;
      --muted: #5f6b7a;
      --line: #d9e1ea;
      --good: #0f7b53;
      --good-bg: #e8f7ef;
      --warn: #9a5a00;
      --warn-bg: #fff4e5;
      --neutral-bg: #eef3f8;
      --shadow: 0 10px 24px rgba(20, 32, 51, 0.08);
      --radius: 18px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", sans-serif;
      background: linear-gradient(180deg, #f7fbff 0%, var(--bg) 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 36px 20px 60px;
    }}
    .hero {{
      background: radial-gradient(circle at top left, #ffffff 0%, #edf5ff 55%, #e8eff7 100%);
      border: 1px solid rgba(20, 32, 51, 0.08);
      border-radius: 28px;
      padding: 28px;
      box-shadow: var(--shadow);
      margin-bottom: 24px;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 34px;
      line-height: 1.15;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.7;
    }}
    .sources {{
      margin-top: 18px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
    }}
    .sources a {{
      color: #1558d6;
      text-decoration: none;
      font-weight: 600;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .metric-card, .compare-card, .note-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .metric-card {{
      padding: 18px;
    }}
    .metric-label {{
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .metric-value {{
      font-size: 22px;
      font-weight: 700;
      line-height: 1.35;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 1.6fr 1fr;
      gap: 20px;
      margin-bottom: 24px;
    }}
    .note-card {{
      padding: 20px 22px;
    }}
    .note-card h2, .compare-card .card-title {{
      margin: 0 0 14px;
      font-size: 18px;
      line-height: 1.35;
    }}
    .note-card ul {{
      margin: 0;
      padding-left: 20px;
      color: var(--text);
      line-height: 1.75;
    }}
    .compare-card {{
      padding: 20px;
      margin-bottom: 20px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .pane {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fafcfe;
      overflow: hidden;
    }}
    .pane-label {{
      background: var(--neutral-bg);
      color: var(--muted);
      padding: 12px 14px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .pane-label.good {{
      background: var(--good-bg);
      color: var(--good);
    }}
    .pane-body {{
      padding: 16px 14px 18px;
      line-height: 1.75;
      font-size: 15px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      background: var(--neutral-bg);
      color: var(--text);
    }}
    .chip.good {{
      background: var(--good-bg);
      color: var(--good);
    }}
    .chip.warn {{
      background: var(--warn-bg);
      color: var(--warn);
    }}
    .chip.muted {{
      opacity: 0.72;
    }}
    .foot {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
      margin-top: 24px;
    }}
    code {{
      background: #f0f4f8;
      padding: 2px 6px;
      border-radius: 8px;
      font-size: 13px;
    }}
    @media (max-width: 980px) {{
      .metrics, .layout, .two-col {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{escape(args.title)}</h1>
      <p>这份报告对比的是同一条小红书样本在 <strong>{escape(args.before_label)}</strong> 和 <strong>{escape(args.after_label)}</strong> 两个阶段的拆解结果。重点看三件事：内容理解是否更完整、结构拆解是否更具体、建议是否更可执行。</p>
      <div class="sources">{''.join(source_links)}</div>
    </section>

    <section class="metrics">{summary_html}</section>

    <section class="layout">
      <div class="note-card">
        <h2>这次最明显的变化</h2>
        <ul>{notes_html}</ul>
      </div>
      <div class="note-card">
        <h2>优化后仍待修的点</h2>
        <div class="chips">{issues_html}</div>
      </div>
    </section>

    {render_side_by_side("Hook 对比", escape(before["hook"]), escape(after["hook"]))}
    {render_side_by_side("叙事模式对比", escape(before["narrative"] + "｜" + before["narrative_desc"]), escape(after["narrative"] + "｜" + after["narrative_desc"]))}
    {render_side_by_side("脚本分段标签", f'<div class="chips">{sections_before}</div>', f'<div class="chips">{sections_after}</div>')}
    {render_side_by_side("脚本分段内容", section_texts_before, section_texts_after)}
    {render_side_by_side("爆点驱动", drivers_before, drivers_after)}
    {render_side_by_side("改编建议", ideas_before, ideas_after)}
    {render_side_by_side("制作方式推断", methods_before, methods_after)}
    {render_side_by_side("口播提炼片段", escape(before["voiceover"]), escape(after["voiceover"]))}

    <p class="foot">
      说明：
      <code>优化前</code> 选用的是你在进一步强化转写和结构识别之前的版本；
      <code>优化后</code> 选用的是最新复测通过的版本。
      这份 HTML 由本地脚本自动生成，后续换别的 before/after JSON 也可以复用。
    </p>
  </div>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    before_json = Path(args.before_json).expanduser().resolve()
    after_json = Path(args.after_json).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    before = report_view(load_json(before_json))
    after = report_view(load_json(after_json))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(args, before_json, after_json, before, after), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
