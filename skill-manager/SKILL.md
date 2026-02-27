---
name: skill-manager
description: Compatibility alias for github-to-skills unified suite. Use when older prompts mention skill-manager; routes to github-to-skills list/check/delete/backup flows.
license: MIT
---

# Skill Manager (Compatibility Alias)

此 Skill 已并入 `github-to-skills`。

请改用统一入口：
```bash
python3 ../github-to-skills/scripts/github_skills_suite.py --help
```

映射关系：
- `scan_and_check.py` -> `github_skills_suite.py check`
- `list_skills.py` -> `github_skills_suite.py list`
- `delete_skill.py` -> `github_skills_suite.py delete`
- `update_helper.py` -> `github_skills_suite.py backup`

