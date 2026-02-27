---
name: github-to-skills
description: Unified GitHub skill suite for creating, managing, and evolving skills. Use when users want to convert a GitHub repo into a skill, list/check/delete local skills, or persist conversation learnings into evolution.json and stitch them back into SKILL.md.
license: MIT
---

# GitHub Skills Suite

这是融合版单一 Skill，合并了：
- `github-to-skills`（GitHub 仓库转 Skill）
- `skill-manager`（盘点/检查更新/删除/备份）
- `skill-evolution-manager`（经验沉淀、缝合、全量对齐）

## 统一入口

```bash
python3 scripts/github_skills_suite.py --help
```

## 核心子命令

### 1) 从 GitHub 生成 Skill
```bash
python3 scripts/github_skills_suite.py create <github_url> --output-dir <skills_dir>
```

### 2) 列出本地技能
```bash
python3 scripts/github_skills_suite.py list --skills-root <skills_root>
```

### 3) 检查 GitHub 技能更新
```bash
python3 scripts/github_skills_suite.py check --skills-root <skills_root>
```

### 4) 删除某个技能
```bash
python3 scripts/github_skills_suite.py delete <skill_name> --skills-root <skills_root>
```

### 5) 备份某个技能的 SKILL.md
```bash
python3 scripts/github_skills_suite.py backup <skill_dir>
```

### 6) 经验沉淀（evolution.json 增量合并）
```bash
python3 scripts/github_skills_suite.py evolve-merge <skill_dir> --json '{"preferences":["..."],"fixes":["..."]}'
```

### 7) 缝合经验到 SKILL.md
```bash
python3 scripts/github_skills_suite.py evolve-stitch <skill_dir>
```

### 8) 全量对齐（批量缝合）
```bash
python3 scripts/github_skills_suite.py evolve-align --skills-root <skills_root>
```

## 兼容脚本（旧入口仍可用）
- `scripts/fetch_github_info.py`
- `scripts/create_github_skill.py`
- `scripts/list_skills.py`
- `scripts/scan_and_check.py`
- `scripts/delete_skill.py`
- `scripts/update_helper.py`
- `scripts/merge_evolution.py`
- `scripts/smart_stitch.py`
- `scripts/align_all.py`

## 统一元数据约定

生成的 Skill 使用 Codex 兼容 frontmatter：

```yaml
---
name: <kebab-case-name>
description: <trigger description>
metadata:
  source:
    github_url: <repo_url>
    github_hash: <latest_hash>
    version: 0.1.0
    created_at: <ISO-8601>
  entry_point: scripts/wrapper.py
  dependencies:
    - <dependency>
---
```

## 触发建议
- 用户说“把这个 GitHub 仓库封装成 skill” -> `create`
- 用户说“查一下我哪些 skill 过期了” -> `check`
- 用户说“复盘并把经验写回 skill” -> `evolve-merge` + `evolve-stitch`

