---
name: claude-mem
description: Manage the locally installed Claude-Mem memory system for Codex transcript capture, worker status, and memory tooling. Use when the user asks to set up, inspect, start, stop, or troubleshoot Claude-Mem, Codex transcript watching, or the local memory viewer.
license: AGPL-3.0
metadata:
  github_url: https://github.com/thedotmack/claude-mem
  github_hash: d06882126fe24f6ebcbe433385daeb8322ba8009
  version: "10.6.3"
  created_at: 2026-03-30T12:00:00+08:00
  entry_point: scripts/status.sh
  dependencies:
    - bun
    - node
    - uv
---

# Claude-Mem For Codex

This is a single-entry wrapper around the upstream `thedotmack/claude-mem` repository.

Use this skill when the user wants to:

- install or verify Claude-Mem locally
- check whether the worker is running
- manage Codex transcript watching
- inspect the local memory viewer and storage paths

## Scope

This wrapper is intentionally a single visible skill entry. It does not expose the upstream repo's internal sub-skills as separate entries in the Codex skill list.

The upstream repo is installed locally and preserved for future updates. This wrapper is tracked by `skill-manager` through the GitHub metadata in frontmatter.

## Important Notes

- Upstream Claude-Mem is primarily built for Claude Code/OpenClaw.
- In this local Codex setup, the useful part is transcript capture from `~/.codex/sessions/**/*.jsonl` plus local worker/viewer management.
- If the user asks "did we do this before?", this wrapper can help verify the local Claude-Mem setup, but native Codex memory retrieval still depends on the local Claude-Mem services being configured and running correctly.
- Any step that needs web search, online documentation lookup, website access, or login-based browser work must call the `web-access` skill. This wrapper should stay focused on local Claude-Mem state and should not bypass that network workflow.

## Local Layout

- Upstream repo: `~/.codex/vendor_imports/claude-mem`
- Transcript config: `~/.claude-mem/transcript-watch.json`
- Worker viewer: `http://localhost:37777`

## Handy Commands

```bash
bash ~/.codex/skills/claude-mem/scripts/status.sh
bash ~/.codex/skills/claude-mem/scripts/init-transcript-watch.sh
bash ~/.codex/skills/claude-mem/scripts/start-worker.sh
bash ~/.codex/skills/claude-mem/scripts/start-transcript-watch.sh
```
