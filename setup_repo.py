#!/usr/bin/env python3
"""One-shot setup: create repo, push, enable Pages.

Usage: python3 setup_repo.py
Requires: gh CLI authenticated, git configured.
"""
import json
import subprocess
import sys
import urllib.request

REPO = "harrytyp/free-llm-tracker"


def run(cmd, **kwargs):
    r = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if r.returncode != 0:
        print(f"FAIL: {' '.join(cmd)}\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def gh_token():
    return run(["gh", "auth", "token"])


def create_repo():
    """Create public repo, ignore if already exists."""
    r = subprocess.run(
        ["gh", "repo", "create", REPO, "--public", "--description",
         "Free LLM API tracker: alle kostenlosen Modelle mit gemessenen t/s und Intelligence-Score"],
        capture_output=True, text=True)
    if r.returncode != 0 and "already exists" not in r.stderr:
        print(r.stderr, file=sys.stderr)
        sys.exit(1)
    print("repo ready:", r.stdout or "already exists")


def push_code():
    """Init git, commit, push to main."""
    run(["git", "init", "-b", "main"])
    run(["git", "remote", "add", "origin", f"https://github.com/{REPO}.git"])
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "feat: initial free-llm-tracker"])
    run(["git", "push", "-u", "origin", "main", "--force"])
    print("pushed")


def enable_pages():
    """Enable GitHub Pages via API (build_type: workflow)."""
    token = gh_token()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/pages",
        data=json.dumps({"build_type": "workflow"}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            print("pages enabled:", resp.status)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("pages already enabled")
        else:
            print(f"pages setup failed {e.code}: {e.read().decode()}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    create_repo()
    push_code()
    enable_pages()
    print("\nDone. Visit: https://github.com/" + REPO)