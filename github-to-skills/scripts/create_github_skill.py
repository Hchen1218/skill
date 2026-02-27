#!/usr/bin/env python3
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


def _safe_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", name.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "github-skill"


def _infer_dependencies(readme: str) -> List[str]:
    text = (readme or "").lower()
    hits: List[str] = []
    for dep in ["python", "node", "npm", "pip", "docker", "ffmpeg", "yt-dlp"]:
        if dep in text:
            hits.append(dep)
    return hits[:8]


def _frontmatter(repo_info: Dict[str, Any], skill_name: str, deps: List[str]) -> str:
    description = repo_info.get("description") or f"Skill wrapper for {repo_info.get('name', skill_name)}"
    description = description.replace("\n", " ").strip()
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    github_hash = repo_info.get("latest_hash") or "unknown"
    github_url = repo_info.get("url") or ""

    dep_yaml = "\n".join([f"    - {d}" for d in deps]) if deps else "    - unknown"

    return f"""---
name: {skill_name}
description: GitHub-derived skill for {repo_info.get('name', skill_name)}. Use when the user asks to run, wrap, or automate this repository's workflow.
metadata:
  source:
    github_url: {github_url}
    github_hash: {github_hash}
    version: 0.1.0
    created_at: {created_at}
    default_branch: {repo_info.get('default_branch', 'main')}
    stars: {repo_info.get('stars', 'unknown')}
    license: {repo_info.get('license', 'unknown')}
  entry_point: scripts/wrapper.py
  dependencies:
{dep_yaml}
---
"""


def create_skill(repo_info: Dict[str, Any], output_dir: str) -> Path:
    repo_name = str(repo_info.get("name") or "github-repo")
    skill_name = _safe_name(repo_name)
    skill_path = Path(output_dir).expanduser().resolve() / skill_name

    (skill_path / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_path / "references").mkdir(parents=True, exist_ok=True)
    (skill_path / "agents").mkdir(parents=True, exist_ok=True)

    readme = str(repo_info.get("readme") or "")
    description = str(repo_info.get("description") or "")
    deps = _infer_dependencies(readme)

    skill_md = _frontmatter(repo_info, skill_name, deps) + f"""
# {repo_name} Skill

## 概览
- 仓库: {repo_info.get('url', '')}
- 描述: {description or 'N/A'}
- 默认分支: {repo_info.get('default_branch', 'main')}
- 最新提交: {repo_info.get('latest_hash', 'unknown')}

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
"""

    (skill_path / "SKILL.md").write_text(skill_md, encoding="utf-8")

    wrapper = f'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wrapper for {repo_name}")
    p.add_argument("--cmd", help="可选：传入要执行的原始命令，例如 'python main.py --help'")
    p.add_argument("--dry-run", action="store_true", help="只打印执行计划")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    plan = {{
        "repo": "{repo_name}",
        "source": "{repo_info.get('url', '')}",
        "latest_hash": "{repo_info.get('latest_hash', 'unknown')}",
        "cmd": args.cmd,
    }}
    if args.dry_run or not args.cmd:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    proc = subprocess.run(args.cmd, shell=True)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
'''

    wrapper_path = skill_path / "scripts" / "wrapper.py"
    wrapper_path.write_text(wrapper, encoding="utf-8")
    try:
        os.chmod(wrapper_path, 0o755)
    except OSError:
        pass

    overview = f"""# Repo Overview

## Source
- URL: {repo_info.get('url', '')}
- Default branch: {repo_info.get('default_branch', 'main')}
- Latest hash: {repo_info.get('latest_hash', 'unknown')}
- Stars: {repo_info.get('stars', 'unknown')}
- License: {repo_info.get('license', 'unknown')}

## README Excerpt

{readme[:8000]}
"""
    (skill_path / "references" / "repo_overview.md").write_text(overview, encoding="utf-8")

    openai_yaml = f'''interface:
  display_name: "{repo_name}"
  short_description: "GitHub 仓库自动生成的技能封装"
  default_prompt: "调用 {repo_name} 的能力完成当前任务，并给出可执行命令。"
'''
    (skill_path / "agents" / "openai.yaml").write_text(openai_yaml, encoding="utf-8")

    return skill_path


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python create_github_skill.py <json_info_file> <output_skills_dir>")
        return 1

    json_file = Path(sys.argv[1]).expanduser().resolve()
    output_dir = sys.argv[2]

    if not json_file.exists():
        print(f"JSON file not found: {json_file}", file=sys.stderr)
        return 1

    repo_info = json.loads(json_file.read_text(encoding="utf-8"))
    if "error" in repo_info:
        print(f"Cannot create skill, repo fetch failed: {repo_info['error']}", file=sys.stderr)
        return 1

    skill_path = create_skill(repo_info, output_dir)
    print(f"Skill scaffolded at: {skill_path}")
    print("Next steps:")
    print("1. Review SKILL.md and refine task-specific instructions.")
    print("2. Implement project-specific logic in scripts/wrapper.py.")
    print(f"3. Validate with: python3 /Users/cecilialiu/.codex/skills/.system/skill-creator/scripts/quick_validate.py {skill_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
