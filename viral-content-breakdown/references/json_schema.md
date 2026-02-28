# report.json Schema（v1）

## Top-level
```json
{
  "meta": {},
  "asset_index": {},
  "engagement_metrics": {},
  "visual_specs": {},
  "post_content": {},
  "hook": {},
  "script_structure": [],
  "narrative_pattern": {},
  "cover_title": {},
  "voiceover_copy": {},
  "production_method_inference": [],
  "virality_drivers": [],
  "adaptation_ideas": [],
  "limitations": [],
  "confidence_overall": 0.0
}
```

## 字段说明
- `meta`
  - `url`: string
  - `platform`: `douyin|xiaohongshu|wechat_mp`
  - `content_type`: `video|image_post|article|unknown`
  - `fetched_at`: ISO8601
  - `published_at`: string（可空）
  - `analyzed_at`: ISO8601
  - `language`: `zh-CN`
  - `analysis_mode`: `llm|fallback`

- `asset_index`
  - `video`: string[]
  - `images`: string[]
  - `audio`: string[]
  - `transcript`: string[]
  - `cover_text`: string[]

- `engagement_metrics`
  - `likes`: number|null
  - `comments`: number|null
  - `plays`: number|null

- `visual_specs`
  - `video_main_aspect_ratio`
    - `value`: string（例如 `9:16`）
    - `width`: number|null
    - `height`: number|null
    - `confidence`: number
  - `subtitle_style_inference`
    - `subtitle_size`: string（推断）
    - `font_style`: string（推断）
    - `confidence`: number
    - `reason`: string

- `post_content`
  - `title`: string
  - `body`: string
  - `tags`: string[]

- `hook`
  - `text`: string
  - `evidence`: Evidence[]

- `script_structure`: array of
  - `section`: string
  - `text`: string
  - `evidence`: Evidence[]

- `narrative_pattern`
  - `name`: string
  - `description`: string
  - `evidence`: Evidence[]

- `cover_title`
  - `text`: string
  - `evidence`: Evidence[]

- `voiceover_copy`
  - `text`: string
  - `evidence`: Evidence[]

- `production_method_inference`: length=3
  - `method`: string
  - `confidence`: number (0~1)
  - `evidence`: Evidence[]

- `virality_drivers`: array
  - `driver`: string
  - `why`: string
  - `evidence`: Evidence[]

- `adaptation_ideas`: array
  - `idea`: string
  - `rationale`: string

- `limitations`: string[]
- `confidence_overall`: number (0~1)

## Evidence
```json
{
  "type": "timestamp|frame_ocr|transcript_span|cover_ocr|visual_pattern",
  "source": "string",
  "locator": "string",
  "snippet": "string",
  "confidence": 0.0
}
```

## 约束
1. 关键结论（`hook`、`virality_drivers`、`production_method_inference`）必须有 evidence。
2. `production_method_inference` 必须输出 Top3，不允许伪造“100%确定”。
3. `adaptation_ideas` 仅给思路，不输出完整复写脚本。
