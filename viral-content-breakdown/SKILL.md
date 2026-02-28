---
name: viral-content-breakdown
description: Analyze Douyin/Xiaohongshu/WeChat article links into evidence-backed JSON + Markdown breakdown reports. Use when users ask for script decomposition, narrative pattern, cover text, voiceover, tags,正文, engagement metrics, visual specs, production-method inference (Top3 confidence), virality reasons, and adaptation ideas.
---

# Viral Content Breakdown

对抖音/小红书/微信公众号单链接执行一线拆解，输出 `report.json` + `report.md`（简体中文，结构化字段，结论附证据）。

## 快速流程
1. 接收自然语言请求并自动识别链接。
2. 执行 `scripts/run_pipeline.py`。
3. 若用户未指定素材保留策略，使用默认 `--save-artifacts ask`。
4. 成功后返回 `report.json` + `report.md` 路径和关键结论摘要。

每条链接会额外导出到固定目录 `./viral_breakdowns/`：
- `<抓取日期>-<内容总结>.json`
- `<抓取日期>-<内容总结>.md`

在不可交互终端（例如 Agent/CI）必须添加 `--non-interactive`，并优先使用 `--save-artifacts always`，避免流程因输入提示而中断。

## 运行命令
```bash
python3 scripts/run_pipeline.py \
  --url "<douyin_or_xhs_or_wechat_url>" \
  --save-artifacts ask \
  --browser safari \
  --session-mode qr-login \
  --quality high
```

自动化/Agent 非交互场景建议：
```bash
python3 scripts/run_pipeline.py \
  --url "<douyin_or_xhs_or_wechat_url>" \
  --save-artifacts always \
  --non-interactive \
  --skip-session
```

## 输入参数约定
- `--url`：必填，单链接。
- `--save-artifacts`：`ask|always|never`，默认 `ask`。
- `--output-dir`：默认 `./viral_breakdowns/<slug>/`（中间产物目录）。
- `--browser`：`safari|chromium`，默认 `safari`。
- `--session-mode`：固定 `qr-login`。
- `--quality`：默认 `high`。
- `--non-interactive`：禁用交互输入，适合 CI/Agent。
- `--session-file`：可选，复用已有 `session.json`。
- `fetch_content.py` 支持 `--input-video/--input-image/--input-audio/--input-transcript` 手动补料。

## 输出与字段
主输出：`report.json`、`report.md`。
核心字段：
- `meta`
- `asset_index`
- `engagement_metrics`（点赞/评论/播放）
- `visual_specs`（视频主画面宽高比、字幕大小/字体推断）
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
- 抖音：优先专用下载器适配器（若本机安装），回退 `yt-dlp`。
- 小红书：优先专用下载器适配器（若本机安装），回退 `yt-dlp`。
- 公众号文章：优先专用适配器（若本机安装），回退 HTML 抽取。
- 仅处理用户有合法访问权限的内容；不实现绕过限制策略。

更多见：`references/platform_notes.md`。
