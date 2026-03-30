---
name: superpowers
description: Use for general software-development tasks when a structured Superpowers workflow would help, or when the user explicitly asks for Superpowers. This is a single entrypoint that chooses the right local Superpowers workflow from /Users/cecilialiu/.codex/.superpowers-internal/skills.
license: MIT
metadata:
  github_url: https://github.com/obra/superpowers
  github_hash: eafe962b18f6c5dc70fb7c8cc7e83e61f4cdde06
  version: "5.0.6"
  created_at: 2026-03-30T12:00:00+08:00
  entry_point: SKILL.md
---

# Superpowers

This is the single-entry wrapper for the local Superpowers toolkit.

Use this skill instead of exposing the underlying Superpowers subskills directly in the main skill list.

User instructions take precedence over this toolkit.

## How To Use This Wrapper

1. Start from the local guide at `/Users/cecilialiu/.codex/.superpowers-internal/skills/using-superpowers/SKILL.md` when the task is broad or process-heavy.
2. Load only the specific underlying workflow files that are relevant to the current task.
3. Keep the user-facing experience simple: refer to this as `superpowers` unless naming an internal workflow is genuinely helpful.
4. Do not force every internal workflow on every task. Pick the smallest useful subset.

## Internal Workflow Map

- Feature idea is vague or still being shaped:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/brainstorming/SKILL.md`
- Design is approved and work needs to be broken down:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/writing-plans/SKILL.md`
- Plan is ready and work should be executed in batches:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/executing-plans/SKILL.md`
- Plan is ready and parallel or delegated execution is appropriate:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/subagent-driven-development/SKILL.md`
- A bug or flaky behavior must be root-caused:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/systematic-debugging/SKILL.md`
- Implementation discipline and tests should drive the work:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/test-driven-development/SKILL.md`
- A branch or change should be reviewed before moving on:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/requesting-code-review/SKILL.md`
- A fix needs confirmation before calling it done:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/verification-before-completion/SKILL.md`
- The task needs isolated git worktree setup:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/using-git-worktrees/SKILL.md`
- The branch is done and should be wrapped up cleanly:
  Read `/Users/cecilialiu/.codex/.superpowers-internal/skills/finishing-a-development-branch/SKILL.md`

## Intent

This wrapper exists to keep the skill list clean while preserving access to the full Superpowers toolkit on disk.
