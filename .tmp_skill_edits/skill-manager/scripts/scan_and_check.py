import os
import sys
import yaml
import json
import subprocess
import concurrent.futures

DEFAULT_SKILL_ROOTS = [
    os.path.expanduser("~/.codex/skills"),
    os.path.expanduser("~/.agents/skills"),
]

COMPANION_ROOTS = {
    os.path.normpath(os.path.expanduser("~/.codex/skills")): [
        os.path.expanduser("~/.agents/skills"),
    ],
}

def extract_github_metadata(frontmatter):
    metadata = frontmatter.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}

    github_url = metadata.get('github_url', frontmatter.get('github_url'))
    github_hash = metadata.get('github_hash', frontmatter.get('github_hash', 'unknown'))
    version = metadata.get('version', frontmatter.get('version', '0.0.0'))

    if not github_url:
        return None

    return {
        "github_url": github_url,
        "github_hash": github_hash,
        "version": version,
    }

def get_remote_hash(url):
    """Fetch the latest commit hash from the remote repository."""
    commands = [
        ['git', 'ls-remote', url, 'HEAD'],
        ['git', '-c', 'http.version=HTTP/1.1', 'ls-remote', url, 'HEAD'],
    ]

    for command in commands:
        try:
            # Using git ls-remote to avoid downloading the whole repo
            # Asking for HEAD specifically
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                continue
            # Output format: <hash>\tHEAD
            parts = result.stdout.split()
            if parts:
                return parts[0]
        except Exception:
            continue

    return None

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

def scan_skills(skill_roots):
    """Scan all subdirectories for SKILL.md and extract metadata."""
    skill_list = []
    seen_dirs = set()

    for skills_root in skill_roots:
        if not os.path.exists(skills_root):
            print(f"Skills root not found: {skills_root}", file=sys.stderr)
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

            skill_md = os.path.join(skill_dir, "SKILL.md")
            if not os.path.exists(skill_md):
                continue

            try:
                with open(skill_md, 'r', encoding='utf-8') as f:
                    content = f.read()

                parts = content.split('---')
                if len(parts) < 3:
                    continue

                frontmatter = yaml.safe_load(parts[1])
                github_meta = extract_github_metadata(frontmatter)
                if github_meta:
                    seen_dirs.add(real_skill_dir)
                    skill_list.append({
                        "name": frontmatter.get('name', item),
                        "dir": skill_dir,
                        "github_url": github_meta['github_url'],
                        "local_hash": github_meta['github_hash'],
                        "local_version": github_meta['version']
                    })
            except Exception:
                pass
            
    return skill_list

def check_updates(skills):
    """Check for updates concurrently."""
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Create a map of future -> skill
        future_to_skill = {
            executor.submit(get_remote_hash, skill['github_url']): skill 
            for skill in skills
        }
        
        for future in concurrent.futures.as_completed(future_to_skill):
            skill = future_to_skill[future]
            try:
                remote_hash = future.result()
                skill['remote_hash'] = remote_hash
                
                if not remote_hash:
                    skill['status'] = 'error'
                    skill['message'] = 'Could not reach remote'
                elif remote_hash != skill['local_hash']:
                    skill['status'] = 'outdated'
                    skill['message'] = 'New commits available'
                else:
                    skill['status'] = 'current'
                    skill['message'] = 'Up to date'
                    
                results.append(skill)
            except Exception as e:
                skill['status'] = 'error'
                skill['message'] = str(e)
                results.append(skill)
                
    return results

if __name__ == "__main__":
    target_dirs = expand_skill_roots(sys.argv[1:])
    if not target_dirs:
        print("Usage: python scan_and_check.py [skills_dir ...]")
        sys.exit(1)

    skills = scan_skills(target_dirs)
    updates = check_updates(skills)
    
    print(json.dumps(updates, indent=2))
