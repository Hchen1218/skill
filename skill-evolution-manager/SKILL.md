---
name: skill-evolution-manager
description: Compatibility alias for github-to-skills unified suite. Use when older prompts mention skill-evolution-manager; routes to evolve-merge/evolve-stitch/evolve-align flows.
license: MIT
---

# Skill Evolution Manager (Compatibility Alias)

此 Skill 已并入 `github-to-skills`。

请改用统一入口：
```bash
python3 ../github-to-skills/scripts/github_skills_suite.py --help
```

映射关系：
- `merge_evolution.py` -> `github_skills_suite.py evolve-merge`
- `smart_stitch.py` -> `github_skills_suite.py evolve-stitch`
- `align_all.py` -> `github_skills_suite.py evolve-align`

