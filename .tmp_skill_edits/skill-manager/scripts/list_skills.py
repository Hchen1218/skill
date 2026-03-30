import os
import sys
import yaml
import io

DEFAULT_SKILL_ROOTS = [
    os.path.expanduser("~/.codex/skills"),
    os.path.expanduser("~/.agents/skills"),
]

COMPANION_ROOTS = {
    os.path.normpath(os.path.expanduser("~/.codex/skills")): [
        os.path.expanduser("~/.agents/skills"),
    ],
}

# Force UTF-8 encoding for stdout to handle Chinese characters on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
else:
    # Fallback for older Python versions
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def extract_github_metadata(meta):
    metadata = meta.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    github_url = metadata.get("github_url", meta.get("github_url"))
    version = metadata.get("version", meta.get("version", "0.1.0"))

    return github_url, version

def expand_skill_roots(raw_roots):
    roots = raw_roots or DEFAULT_SKILL_ROOTS
    expanded = []
    seen = set()

    for root in roots:
        normalized = os.path.normpath(os.path.abspath(os.path.expanduser(root)))
        candidate_roots = [normalized]
        candidate_roots.extend(
            os.path.normpath(os.path.abspath(os.path.expanduser(path)))
            for path in COMPANION_ROOTS.get(normalized, [])
        )

        for candidate in candidate_roots:
            if candidate in seen or not os.path.exists(candidate):
                continue
            seen.add(candidate)
            expanded.append(candidate)

    return expanded

def collect_skills(skill_roots):
    rows = []
    seen_dirs = set()

    for skills_root in skill_roots:
        if not os.path.exists(skills_root):
            print(f"Error: {skills_root} not found")
            continue

        for item in sorted(os.listdir(skills_root)):
            if item.startswith('.'):
                continue

            skill_dir = os.path.join(skills_root, item)
            if not os.path.isdir(skill_dir):
                continue

            real_skill_dir = os.path.realpath(skill_dir)
            if real_skill_dir in seen_dirs:
                continue
            seen_dirs.add(real_skill_dir)

            skill_md = os.path.join(skill_dir, "SKILL.md")
            skill_type = "Standard"
            version = "0.1.0"
            description = "No description"
            display_name = item

            if os.path.exists(skill_md):
                try:
                    with open(skill_md, "r", encoding="utf-8") as f:
                        content = f.read()
                    parts = content.split("---")
                    if len(parts) >= 3:
                        meta = yaml.safe_load(parts[1])
                        github_url, version = extract_github_metadata(meta)
                        if github_url:
                            skill_type = "GitHub"
                        version = str(version)
                        display_name = meta.get("name", item)
                        description = meta.get("description", "No description").replace('\n', ' ')
                except Exception:
                    pass

            rows.append((display_name, skill_type, description, version))

    return sorted(rows, key=lambda row: row[0])

def list_skills(skill_roots):
    rows = collect_skills(skill_roots)

    # Header with Description column
    header = f"{'Skill Name':<20} | {'Type':<12} | {'Description':<40} | {'Ver':<8}"
    print(header)
    print("-" * len(header))

    for item, skill_type, description, version in rows:
        if len(description) > 37:
            display_desc = description[:37] + "..."
        else:
            display_desc = description

        print(f"{item:<20} | {skill_type:<12} | {display_desc:<40} | {version:<8}")

if __name__ == "__main__":
    list_skills(expand_skill_roots(sys.argv[1:]))
