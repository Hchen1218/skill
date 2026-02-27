#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def _default_skills_root() -> Path:
    return Path.home() / ".codex" / "skills"


def _extract_frontmatter(content: str) -> Dict[str, Any]:
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_skill_meta(skill_dir: Path) -> Dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {}
    content = skill_md.read_text(encoding="utf-8", errors="ignore")
    return _extract_frontmatter(content)


def _source_meta(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    source = ((frontmatter.get("metadata") or {}).get("source") or {}) if isinstance(frontmatter, dict) else {}
    if not isinstance(source, dict):
        source = {}
    # backward compatible fields
    if "github_url" not in source and frontmatter.get("github_url"):
        source["github_url"] = frontmatter.get("github_url")
    if "github_hash" not in source and frontmatter.get("github_hash"):
        source["github_hash"] = frontmatter.get("github_hash")
    if "version" not in source and frontmatter.get("version"):
        source["version"] = frontmatter.get("version")
    return source


def _git_remote_hash(repo_url: str) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "ls-remote", repo_url, "HEAD"],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return None
        return res.stdout.split()[0]
    except Exception:
        return None


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.skills_root).expanduser().resolve()
    if not root.exists():
        print(json.dumps({"error": f"skills_root_not_found: {root}"}, ensure_ascii=False, indent=2))
        return 1

    rows: List[Dict[str, Any]] = []
    for item in sorted(root.iterdir(), key=lambda p: p.name):
        if not item.is_dir():
            continue
        fm = _load_skill_meta(item)
        if not fm:
            continue
        source = _source_meta(fm)
        rows.append(
            {
                "name": fm.get("name", item.name),
                "description": fm.get("description", ""),
                "path": str(item),
                "github_url": source.get("github_url"),
                "github_hash": source.get("github_hash"),
                "version": source.get("version", "0.1.0"),
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.skills_root).expanduser().resolve()
    if not root.exists():
        print(json.dumps({"error": f"skills_root_not_found: {root}"}, ensure_ascii=False, indent=2))
        return 1

    skills: List[Dict[str, Any]] = []
    for item in sorted(root.iterdir(), key=lambda p: p.name):
        if not item.is_dir():
            continue
        fm = _load_skill_meta(item)
        if not fm:
            continue
        source = _source_meta(fm)
        if not source.get("github_url"):
            continue
        skills.append(
            {
                "name": fm.get("name", item.name),
                "path": str(item),
                "github_url": source.get("github_url"),
                "local_hash": source.get("github_hash", "unknown"),
                "version": source.get("version", "0.1.0"),
            }
        )

    def _one(skill: Dict[str, Any]) -> Dict[str, Any]:
        remote = _git_remote_hash(skill["github_url"])
        out = dict(skill)
        out["remote_hash"] = remote
        if not remote:
            out["status"] = "error"
            out["message"] = "cannot_reach_remote"
        elif remote != skill["local_hash"]:
            out["status"] = "outdated"
            out["message"] = "new_commits_available"
        else:
            out["status"] = "current"
            out["message"] = "up_to_date"
        return out

    results: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, min(8, len(skills) or 2))) as ex:
        futs = [ex.submit(_one, s) for s in skills]
        for fut in concurrent.futures.as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda x: x["name"])
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    root = Path(args.skills_root).expanduser().resolve()
    skill_dir = root / args.skill_name
    if not skill_dir.exists():
        print(json.dumps({"error": f"skill_not_found: {skill_dir}"}, ensure_ascii=False, indent=2))
        return 1
    shutil.rmtree(skill_dir)
    print(json.dumps({"ok": True, "deleted": str(skill_dir)}, ensure_ascii=False, indent=2))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        print(json.dumps({"error": f"SKILL.md_not_found: {skill_md}"}, ensure_ascii=False, indent=2))
        return 1
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = skill_dir / f"SKILL.md.bak.{ts}"
    shutil.copy2(skill_md, bak)
    print(json.dumps({"ok": True, "backup": str(bak)}, ensure_ascii=False, indent=2))
    return 0


def _merge_lists(dst: List[Any], src: List[Any]) -> List[Any]:
    out = list(dst)
    for item in src:
        if item not in out:
            out.append(item)
    return out


def cmd_evolve_merge(args: argparse.Namespace) -> int:
    skill_dir = Path(args.skill_dir).expanduser().resolve()
    evo_path = skill_dir / "evolution.json"
    current: Dict[str, Any] = {}
    if evo_path.exists():
        try:
            current = json.loads(evo_path.read_text(encoding="utf-8"))
        except Exception:
            current = {}

    new_data: Dict[str, Any] = {}
    if args.json:
        new_data = json.loads(args.json)
    elif args.json_file:
        new_data = json.loads(Path(args.json_file).expanduser().read_text(encoding="utf-8"))

    current["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for key in ["preferences", "fixes", "contexts"]:
        if key in new_data and isinstance(new_data[key], list):
            current[key] = _merge_lists(current.get(key, []), new_data[key])
    if "custom_prompts" in new_data:
        current["custom_prompts"] = new_data["custom_prompts"]
    if "last_evolved_hash" in new_data:
        current["last_evolved_hash"] = new_data["last_evolved_hash"]

    evo_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "evolution": str(evo_path)}, ensure_ascii=False, indent=2))
    return 0


def _render_evolution_block(data: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("## User-Learned Best Practices & Constraints")
    lines.append("")
    lines.append("> **Auto-Generated Section**: This section is maintained by github-to-skills evolution tools.")
    if data.get("preferences"):
        lines.append("")
        lines.append("### User Preferences")
        for x in data["preferences"]:
            lines.append(f"- {x}")
    if data.get("fixes"):
        lines.append("")
        lines.append("### Known Fixes & Workarounds")
        for x in data["fixes"]:
            lines.append(f"- {x}")
    if data.get("contexts"):
        lines.append("")
        lines.append("### Context Notes")
        for x in data["contexts"]:
            lines.append(f"- {x}")
    if data.get("custom_prompts"):
        lines.append("")
        lines.append("### Custom Instruction Injection")
        lines.append("")
        lines.append(str(data["custom_prompts"]))
    lines.append("")
    return "\n".join(lines)


def cmd_evolve_stitch(args: argparse.Namespace) -> int:
    skill_dir = Path(args.skill_dir).expanduser().resolve()
    skill_md = skill_dir / "SKILL.md"
    evo_path = skill_dir / "evolution.json"
    if not skill_md.exists() or not evo_path.exists():
        print(json.dumps({"ok": True, "skipped": str(skill_dir), "reason": "missing_SKILL_or_evolution"}, ensure_ascii=False, indent=2))
        return 0

    data = json.loads(evo_path.read_text(encoding="utf-8"))
    content = skill_md.read_text(encoding="utf-8")
    block = _render_evolution_block(data)

    pattern = re.compile(r"\n+## User-Learned Best Practices & Constraints[\s\S]*$", re.MULTILINE)
    if pattern.search(content):
        new_content = pattern.sub("\n\n" + block + "\n", content)
    else:
        suffix = "\n" if content.endswith("\n") else "\n\n"
        new_content = content + suffix + block + "\n"

    skill_md.write_text(new_content, encoding="utf-8")
    print(json.dumps({"ok": True, "stitched": str(skill_md)}, ensure_ascii=False, indent=2))
    return 0


def cmd_evolve_align(args: argparse.Namespace) -> int:
    root = Path(args.skills_root).expanduser().resolve()
    if not root.exists():
        print(json.dumps({"error": f"skills_root_not_found: {root}"}, ensure_ascii=False, indent=2))
        return 1

    stitched: List[str] = []
    for item in sorted(root.iterdir(), key=lambda p: p.name):
        if not item.is_dir():
            continue
        evo = item / "evolution.json"
        md = item / "SKILL.md"
        if evo.exists() and md.exists():
            subargs = argparse.Namespace(skill_dir=str(item))
            rc = cmd_evolve_stitch(subargs)
            if rc == 0:
                stitched.append(item.name)

    print(json.dumps({"ok": True, "aligned": stitched}, ensure_ascii=False, indent=2))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    from fetch_github_info import get_repo_info
    from create_github_skill import create_skill

    info = get_repo_info(args.github_url, token=args.github_token)
    skill_path = create_skill(info, args.output_dir)
    print(json.dumps({"ok": True, "skill_path": str(skill_path), "repo": info.get("url")}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified GitHub skill suite: create + manage + evolve")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create a skill from GitHub repository")
    p_create.add_argument("github_url")
    p_create.add_argument("--output-dir", required=True)
    p_create.add_argument("--github-token")
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="List local skills")
    p_list.add_argument("--skills-root", default=str(_default_skills_root()))
    p_list.set_defaults(func=cmd_list)

    p_check = sub.add_parser("check", help="Check GitHub-based skills for updates")
    p_check.add_argument("--skills-root", default=str(_default_skills_root()))
    p_check.set_defaults(func=cmd_check)

    p_del = sub.add_parser("delete", help="Delete one skill folder")
    p_del.add_argument("skill_name")
    p_del.add_argument("--skills-root", default=str(_default_skills_root()))
    p_del.set_defaults(func=cmd_delete)

    p_backup = sub.add_parser("backup", help="Backup SKILL.md before manual edit")
    p_backup.add_argument("skill_dir")
    p_backup.set_defaults(func=cmd_backup)

    p_em = sub.add_parser("evolve-merge", help="Merge new evolution JSON into evolution.json")
    p_em.add_argument("skill_dir")
    g = p_em.add_mutually_exclusive_group(required=True)
    g.add_argument("--json")
    g.add_argument("--json-file")
    p_em.set_defaults(func=cmd_evolve_merge)

    p_es = sub.add_parser("evolve-stitch", help="Stitch evolution.json into SKILL.md")
    p_es.add_argument("skill_dir")
    p_es.set_defaults(func=cmd_evolve_stitch)

    p_ea = sub.add_parser("evolve-align", help="Align all skills by re-stitching evolution blocks")
    p_ea.add_argument("--skills-root", default=str(_default_skills_root()))
    p_ea.set_defaults(func=cmd_evolve_align)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
