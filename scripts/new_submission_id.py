#!/usr/bin/env python3
"""Create (or reuse) this run's anonymous SUBMISSION_ID.

usage: python scripts/new_submission_id.py

* If the current branch is already submit/<id>, prints that <id> (use this when a run is
  split over several sessions).
* Otherwise generates a random id like `anon-3f9c1a`, creates branch submit/<id>,
  sets an anonymous git identity for this clone, and creates submissions/<id>/meta.json.
Prints only the id on the last line.
"""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def main() -> None:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch.startswith("submit/"):
        sid = branch[len("submit/"):]
        print(f"already on {branch}; reusing this id")
    else:
        if git("status", "--porcelain"):
            sys.exit("working tree is not clean; start from a fresh clone")
        sid = "anon-" + secrets.token_hex(3)
        git("checkout", "-b", f"submit/{sid}")
        print(f"created branch submit/{sid}")
    # anonymous identity for every commit made in this clone
    git("config", "user.name", "anon")
    git("config", "user.email", "anon@bench.invalid")
    sub = ROOT / "submissions" / sid
    sub.mkdir(parents=True, exist_ok=True)
    meta = sub / "meta.json"
    if not meta.exists():
        m = json.loads((ROOT / "submissions" / "_template" / "meta.json").read_text(encoding="utf-8"))
        m["submission_id"] = sid
        meta.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"created {meta.relative_to(ROOT)}")
    print(sid)


if __name__ == "__main__":
    main()
