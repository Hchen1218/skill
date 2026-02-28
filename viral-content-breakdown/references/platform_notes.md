# Platform Notes（抖音/小红书/公众号）

## 下载策略
- 抖音：优先专用适配器（`douyin-downloader` / `res-downloader`），失败回退 `yt-dlp`。
- 小红书：先尝试专用适配器（`xhs-downloader` / `rednote-video-assist` / `xhsdl` / `res-downloader`），失败回退 `yt-dlp`。
- 公众号文章：优先专用适配器（`wechat-article-exporter` / `res-downloader`），失败回退 HTML 抽取。
- 所有失败均写入结构化错误，字段包括：`code`、`reason`、`next_action`。

## 会话策略
- 默认 `qr-login`。
- `browser=safari`：打开 Safari 扫码登录，建议配合 cookies 文件提高下载成功率。
- `browser=chromium`：打开 Chrome 扫码登录，并在 session 文件中记录浏览器来源。
- 浏览器 Cookie 自动读取优先；无法读取时可手动提供 `cookies.txt`。
- 会话文件权限建议 600。

## 图文/视频兼容
- 视频：抽帧 + OCR + ASR/字幕。
- 图文：图片 OCR + 文案文本抽取。
- 公众号：HTML 正文抽取 + 元数据提取（标题/正文/标签/封面）。
- 当 OCR/ASR 缺失时，不中断主流程，进入降级分析并标注 `limitations`。

## 目标输出
- 每条链接独立产物：`report.json` + `report.md`。
- 统一导出到 `./viral_breakdowns`，文件名：`<抓取日期>-<内容总结>.json/.md`。
- 必含字段：热度（点赞/评论/播放）、标题、封面标题、Tag、正文、口播、字幕大小、字体格式、视频主画面宽高比、软件推断 Top3。

## 依赖建议
```bash
brew install yt-dlp ffmpeg tesseract
python3 -m pip install openai
```

## GitHub 高热项目（适配器候选）
以下项目用于“优先开源适配器”策略：

1. `yt-dlp/yt-dlp`
   - 链接：<https://github.com/yt-dlp/yt-dlp>
   - 用途：全平台回退下载引擎。
2. `putyy/res-downloader`
   - 链接：<https://github.com/putyy/res-downloader>
   - 用途：多平台资源抓取（抖音/小红书/视频号等）。
3. `JoeanAmier/XHS-Downloader`
   - 链接：<https://github.com/JoeanAmier/XHS-Downloader>
   - 用途：小红书专用采集/下载。
4. `jiji262/douyin-downloader`
   - 链接：<https://github.com/jiji262/douyin-downloader>
   - 用途：抖音批量下载与 Cookie 流程。
5. `wechat-article/wechat-article-exporter`
   - 链接：<https://github.com/wechat-article/wechat-article-exporter>
   - 用途：公众号文章导出（含阅读量/评论扩展能力）。

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
4. 热度字段为空
   - 某些平台在未登录/反爬场景下不返回互动计数
   - 会在 `limitations` 中声明，不伪造数据

## 合规提示
仅处理用户有合法访问权限的公开或授权内容。遇到受限内容应返回失败原因，不做绕过策略。
