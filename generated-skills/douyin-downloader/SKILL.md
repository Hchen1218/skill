---
name: douyin-downloader
description: GitHub-derived skill for douyin-downloader. Use when the user asks to run, wrap, or automate this repository's workflow.
metadata:
  source:
    github_url: https://github.com/jiji262/douyin-downloader
    github_hash: unknown
    version: 0.1.0
    created_at: 2026-02-27T05:51:56.167973+00:00
    default_branch: main
    stars: None
    license: None
  entry_point: scripts/wrapper.py
  dependencies:
    - unknown
---

# douyin-downloader Skill

## 概览
- 仓库: https://github.com/jiji262/douyin-downloader
- 描述: N/A
- 默认分支: main
- 最新提交: unknown

## 推荐流程
1. 先阅读 `references/repo_overview.md` 的关键命令与入口信息。
2. 调用 `scripts/wrapper.py` 作为统一入口。
3. 若执行失败，先检查依赖（见 frontmatter metadata.dependencies）。

## 统一入口
```bash
python3 scripts/wrapper.py --help
```

## 注意
- 这是自动生成的初始 skill，请根据你的项目补充更具体的调用参数。
- 如上游仓库更新，可重新运行 github-to-skills 刷新 `github_hash`。
