---
name: viral-content-breakdown
description: Analyze Douyin and Xiaohongshu single links into evidence-backed JSON breakdown reports. Use when a user shares a viral short-video or image-post URL and wants script decomposition, narrative pattern, cover title text, voiceover extraction, hook analysis, production-method inference (Top3 with confidence), virality reasons, and adaptation ideas (without full rewrite). 当用户提供抖音/小红书链接并要求拆解爆款视频或图文（脚本、叙事、口播、封面文案、标题、正文、tag、爆点原因、可复用改写思路）时使用。
---

# Viral Content Breakdown

对抖音/小红书单链接执行一线拆解，输出 `report.json`（简体中文，结构化字段，结论附证据）。

## 快速流程
1. 接收自然语言请求并自动识别链接。
2. 执行 `scripts/run_pipeline.py`。
3. 若用户未指定素材保留策略，使用默认 `--save-artifacts ask`。
4. 成功后返回 `report.json` 路径和关键结论摘要。

在不可交互终端（例如 Agent/CI）必须添加 `--non-interactive`，并优先使用 `--save-artifacts always`，避免流程因输入提示而中断。

## 运行命令
```bash
python3 scripts/run_pipeline.py \
  --url "<douyin_or_xhs_url>" \
  --save-artifacts ask \
  --browser safari \
  --session-mode qr-login \
  --quality high
```

自动化/Agent 非交互场景建议：
```bash
python3 scripts/run_pipeline.py \
  --url "<douyin_or_xhs_url>" \
  --save-artifacts always \
  --non-interactive \
  --skip-session
```

## 输入参数约定
- `--url`：必填，单链接。
- `--save-artifacts`：`ask|always|never`，默认 `ask`。
- `--output-dir`：默认 `./viral_breakdowns/<slug>/`。
- `--browser`：`safari|chromium`，默认 `safari`。
- `--session-mode`：固定 `qr-login`。
- `--quality`：默认 `high`。
- `--non-interactive`：禁用交互输入，适合 CI/Agent。
- `--session-file`：可选，复用已有 `session.json`。

## 输出与字段
主输出：`report.json`。
核心字段：
- `meta`
- `asset_index`
- `post_content`（正文/标题/tag）
- `hook`
- `script_structure`
- `narrative_pattern`
- `cover_title`
- `voiceover_copy`
- `production_method_inference`（Top3 + confidence）
- `virality_drivers`
- `adaptation_ideas`（思路，不给完整改写稿）
- `limitations`
- `confidence_overall`

证据对象统一格式：
- `evidence: [{type, source, locator, snippet, confidence}]`
- `type` 仅允许：`timestamp | frame_ocr | transcript_span | cover_ocr | visual_pattern`

详情见：`references/json_schema.md`。

## 依赖
建议安装：
```bash
brew install yt-dlp ffmpeg tesseract
python3 -m pip install openai
```

- 无 `OPENAI_API_KEY` 时，分析层自动降级为规则分析，仍输出完整 schema。
- 无 `tesseract` 或 `ffmpeg` 时，相关字段降级并在 `limitations` 标注。

## 失败与降级策略
- 下载失败：`fetch_content.py` 写结构化错误（`reason` + `next_action`）。
- OCR/ASR 失败：保留已有证据，补充限制说明，不中断整体输出。
- 会话失效：重新执行扫码登录步骤。
- DNS/网络受限：错误里会标注“网络或 DNS 无法解析平台域名”。

## 平台说明
- 抖音：优先 `yt-dlp`。
- 小红书：优先专用下载器适配器，失败回退 `yt-dlp`。
- 仅处理用户有合法访问权限的内容；不实现绕过限制策略。

更多见：`references/platform_notes.md`。
