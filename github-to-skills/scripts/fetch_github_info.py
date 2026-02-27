#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import urllib.request
from typing import Any, Dict, Optional, Tuple


def _normalize_repo_url(url: str) -> Tuple[str, str, str]:
    clean = url.strip().rstrip("/")
    if clean.endswith(".git"):
        clean = clean[:-4]

    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+)$", clean)
    if not m:
        raise ValueError(f"Invalid GitHub URL: {url}")

    owner = m.group(1)
    repo = m.group(2)
    canonical = f"https://github.com/{owner}/{repo}"
    return owner, repo, canonical


def _http_get_json(url: str, token: Optional[str] = None) -> Dict[str, Any]:
    headers = {"User-Agent": "github-to-skills/1.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url: str, token: Optional[str] = None) -> str:
    headers = {"User-Agent": "github-to-skills/1.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _latest_hash_via_git(repo_url: str) -> str:
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.split()[0]
    except Exception:
        return "unknown"


def _readme_via_raw(owner: str, repo: str) -> str:
    for branch in ("main", "master"):
        for name in ("README.md", "readme.md", "README.MD"):
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{name}"
            try:
                return _http_get_text(raw_url)
            except Exception:
                continue
    return ""


def get_repo_info(url: str, token: Optional[str] = None) -> Dict[str, Any]:
    owner, repo, canonical = _normalize_repo_url(url)

    latest_hash = "unknown"
    readme = ""
    description = ""
    default_branch = "main"
    stars = None
    license_name = None
    homepage = None

    try:
        repo_api = f"https://api.github.com/repos/{owner}/{repo}"
        repo_json = _http_get_json(repo_api, token=token)
        description = repo_json.get("description") or ""
        default_branch = repo_json.get("default_branch") or "main"
        stars = repo_json.get("stargazers_count")
        homepage = repo_json.get("homepage")
        license_obj = repo_json.get("license") or {}
        if isinstance(license_obj, dict):
            license_name = license_obj.get("spdx_id") or license_obj.get("name")
    except Exception as exc:
        print(f"Warning: repo API fetch failed: {exc}", file=sys.stderr)

    try:
        commit_api = f"https://api.github.com/repos/{owner}/{repo}/commits/{default_branch}"
        commit_json = _http_get_json(commit_api, token=token)
        latest_hash = commit_json.get("sha") or "unknown"
    except Exception:
        latest_hash = _latest_hash_via_git(canonical)

    try:
        readme_api = f"https://api.github.com/repos/{owner}/{repo}/readme"
        readme_json = _http_get_json(readme_api, token=token)
        content = readme_json.get("content")
        encoding = readme_json.get("encoding")
        if content and encoding == "base64":
            readme = base64.b64decode(content).decode("utf-8", errors="ignore")
    except Exception:
        readme = ""

    if not readme:
        readme = _readme_via_raw(owner, repo)

    return {
        "name": repo,
        "owner": owner,
        "repo": repo,
        "url": canonical,
        "description": description,
        "default_branch": default_branch,
        "latest_hash": latest_hash,
        "license": license_name,
        "stars": stars,
        "homepage": homepage,
        "readme": readme[:20000],
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python fetch_github_info.py <github_url> [github_token]", file=sys.stderr)
        return 1

    url = sys.argv[1]
    token = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        info = get_repo_info(url, token=token)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "url": url}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
