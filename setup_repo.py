#!/usr/bin/env python3
"""One-shot: create repo, push, enable Pages."""
import json
import subprocess
import sys
import urllib.request

REPO = "harrytyp/free-llm-tracker"


def gh(*args, input_text=None):
    cmd = ["gh", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    if r.returncode != 0:
        print(f"gh {' '.join(args)} failed:\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


# 1. Create repo (idempotent: ignore 'already exists')
r = subprocess.run(
    ["gh", "repo", "create", REPO, "--public", "--description",
     "Free LLM API tracker: alle kostenlosen Modelle mit gemessenen t/s und Intelligence-Score"],
    capture_output=True, text=True)
if r.returncode != 0 and "already exists" not in r.stderr:
    print(r.stderr, file=sys.stderr)
    sys.exit(1)
print("repo ready:", r.stdout or "already exists")

# 2. Push code
subprocess.run(["git", "init", "-b", "main"], check=True)
subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{REPO}.git"], check=True)
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(["git", "commit", "-m", "feat: initial free-llm-tracker"], check=True)
subprocess.run(["git", "push", "-u", "origin", "main", "--force"], check=True)
print("pushed")

# 3. Enable Pages via API (source: github-actions)
token = subprocess.run(
    ["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
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
    body = e.read().decode()
    if e.code == 409:  # already exists
        print("pages already enabled")
    else:
        print(f"pages setup failed {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
