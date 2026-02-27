# Platform Notes（抖音/小红书）

## 下载策略
- 抖音：优先 `yt-dlp`。
- 小红书：先尝试专用适配器（`xhs-downloader` / `rednote-video-assist` / `xhsdl`），失败后回退 `yt-dlp`。
- 所有失败均写入结构化错误，字段包括：`code`、`reason`、`next_action`。

## 会话策略
- 默认 `qr-login`。
- `browser=safari`：打开 Safari 扫码登录，建议配合 cookies 文件提高下载成功率。
- `browser=chromium`：打开 Chrome 扫码登录，并在 session 文件中记录浏览器来源。
- 会话文件权限建议 600。

## 图文/视频兼容
- 视频：抽帧 + OCR + ASR/字幕。
- 图文：图片 OCR + 文案文本抽取。
- 当 OCR/ASR 缺失时，不中断主流程，进入降级分析并标注 `limitations`。

## 依赖建议
```bash
brew install yt-dlp ffmpeg tesseract
python3 -m pip install openai
```

## 常见问题
1. 下载失败（私密/删除/限流）
   - 检查链接是否可访问
   - 刷新登录态并重新扫码
   - 更新 `yt-dlp` 与专用下载器版本
2. 无口播文本
   - 确认音频轨存在
   - 检查 `ffmpeg` 可用
   - 设置 `OPENAI_API_KEY` 启用 ASR
3. OCR 文本缺失
   - 检查 `tesseract` 安装
   - 提高素材清晰度或换高分辨率源文件

## 合规提示
仅处理用户有合法访问权限的公开或授权内容。遇到受限内容应返回失败原因，不做绕过策略。
