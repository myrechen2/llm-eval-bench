#!/usr/bin/env python3
"""Format self-check for a submission. It does NOT know the correct answers.

usage: python scripts/check_submission.py <SUBMISSION_ID>
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ok = True


def report(cond: bool, msg: str) -> None:
    global ok
    print(("  [ok]   " if cond else "  [FAIL] ") + msg)
    ok &= cond


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        report(False, f"{p.relative_to(ROOT)} is not valid JSON: {e}")
        return None


def is_grid(g) -> bool:
    return (isinstance(g, list) and len(g) > 0 and all(isinstance(r, list) and len(r) == len(g[0]) and len(r) > 0
            and all(isinstance(v, int) and 0 <= v <= 9 for v in r) for r in g))


IDENTITY_RX = re.compile(
    r"gemini|claude|anthropic|openai|chatgpt|\bgpt[-\s]?\d|\bgpt\b|codex|copilot|deepmind|\bgoogle\b|\bbard\b"
    r"|qwen|deepseek|llama|\bgrok\b|mistral|\bkimi\b|moonshot|\bglm\b|zhipu|doubao|ernie|\bopus\b|\bsonnet\b"
    r"|\bhaiku\b|antigravity|\bjules\b|thinking[_ -]?(level|budget)|reasoning[_ -]?effort|co-authored-by"
    r"|generated with|思考强度|思考预算|推理强度",
    re.IGNORECASE,
)


def anonymity_checks(sub: Path, sid: str) -> None:
    hits = []
    for f in sorted(sub.rglob("*")):
        if not f.is_file() or f.stat().st_size > 5_000_000:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            m = IDENTITY_RX.search(line)
            if m:
                hits.append(f"{f.relative_to(ROOT)}:{n}: ...{line[max(0, m.start() - 30):m.end() + 30].strip()}...")
    report(not hits, "no model/vendor/tool/thinking-level mentions in submission files"
           + ("" if not hits else "\n" + "\n".join("           " + h for h in hits[:20])))

    def git(*a):
        r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None

    branch = (git("rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    report(branch == f"submit/{sid}", f"on branch submit/{sid} (current: {branch or '?'})")
    base = "origin/main" if git("rev-parse", "--verify", "-q", "origin/main") else "main"
    log = git("log", "--format=%an <%ae>%n%B%n----", f"{base}..HEAD")
    if log is None:
        report(False, "could not read git log")
        return
    bad = [l for l in log.splitlines() if IDENTITY_RX.search(l)]
    authors = {l for l in log.splitlines() if l.endswith(">") and "<" in l}
    ok_authors = authors <= {"anon <anon@bench.invalid>"}
    fix = (f"\n           fix (squashes your commits into one, anonymous):\n"
           f"             git reset --soft $(git merge-base HEAD {base}) && "
           f"git -c user.name=anon -c user.email=anon@bench.invalid commit -m \"{sid}: submission\"")
    report(not bad, "commit messages contain no identifying text" + ("" if not bad else "\n           " + "\n           ".join(bad[:10]) + fix))
    report(ok_authors, "all commits authored as anon <anon@bench.invalid>" + ("" if ok_authors else f" (found: {sorted(authors)})" + fix))


def main(sid: str) -> int:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", sid):
        print("SUBMISSION_ID should match [a-z0-9][a-z0-9._-]* (lower case)")
        return 2
    sub = ROOT / "submissions" / sid
    print(f"checking {sub.relative_to(ROOT)}")
    report(sub.is_dir(), "submission directory exists")
    if not sub.is_dir():
        return 1

    meta = sub / "meta.json"
    report(meta.is_file(), "meta.json exists")
    if meta.is_file():
        m = load_json(meta)
        if m is not None:
            report(m.get("submission_id") == sid, "meta.json submission_id matches")

    print("task 01")
    proj = sub / "01-swe-cellcalc" / "project"
    report((proj / "cellcalc" / "sheet.py").is_file(), "project copied to 01-swe-cellcalc/project")
    report((sub / "01-swe-cellcalc" / "NOTES.md").is_file(), "01 NOTES.md exists")
    if (proj / "tests").is_dir():
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=proj,
                           capture_output=True, text=True, timeout=600)
        report(r.returncode == 0, "public tests pass" + ("" if r.returncode == 0 else "\n" + r.stderr[-1500:]))

    print("task 02")
    a2 = sub / "02-log-forensics" / "answers.json"
    report(a2.is_file(), "02 answers.json exists")
    if a2.is_file():
        a = load_json(a2) or {}
        for k, typ in [("culprit_deploy_id", str), ("mitigation_deploy_id", str), ("first_extra_charge_utc", str),
                       ("orders_needing_refund", int), ("outstanding_refund_minor", dict), ("top_user", dict),
                       ("gateway_checkout_502_in_window", int), ("charge_result_stats", dict)]:
            report(isinstance(a.get(k), typ), f"02 answers.{k} is {typ.__name__}")
        if isinstance(a.get("outstanding_refund_minor"), dict):
            report(set(a["outstanding_refund_minor"]) == {"CNY", "USD"}, "02 outstanding_refund_minor has CNY and USD")
        if isinstance(a.get("charge_result_stats"), dict):
            report(set(a["charge_result_stats"]) == {"before_p95_ms", "during_p95_ms", "during_timeout_rate_pct"},
                   "02 charge_result_stats keys")
        if isinstance(a.get("first_extra_charge_utc"), str):
            report(bool(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", a["first_extra_charge_utc"])),
                   "02 first_extra_charge_utc format")
    report((sub / "02-log-forensics" / "REPORT.md").is_file(), "02 REPORT.md exists")

    print("task 03")
    a3 = sub / "03-math-reasoning" / "answers.json"
    report(a3.is_file(), "03 answers.json exists")
    if a3.is_file():
        a = load_json(a3) or {}
        ans = a.get("answers", {})
        report(isinstance(ans, dict) and all(isinstance(ans.get(str(i)), int) for i in range(1, 9)),
               "03 answers 1..8 are integers")
        report(isinstance(a.get("used_tools"), bool), "03 used_tools is a boolean")
    report((sub / "03-math-reasoning" / "solutions.md").is_file(), "03 solutions.md exists")

    print("task 04")
    a4 = sub / "04-arc-puzzles" / "answers.json"
    report(a4.is_file(), "04 answers.json exists")
    if a4.is_file():
        a = load_json(a4) or {}
        for i in range(1, 11):
            pid = f"{i:02d}"
            e = a.get(pid)
            good = isinstance(e, dict) and is_grid(e.get("attempt_1")) and (
                e.get("attempt_2") is None or is_grid(e.get("attempt_2")))
            report(good, f"04 puzzle {pid} has a valid attempt_1 grid (attempt_2 grid or null)")

    print("task 05")
    h = sub / "05-frontend-metro" / "index.html"
    report(h.is_file(), "05 index.html exists")
    if h.is_file():
        src = h.read_text(encoding="utf-8", errors="replace")
        ext = re.findall(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//""", src) + re.findall(r"@import\s+url\(\s*['\"]?https?:", src)
        report(not ext, "05 no external src/href/@import")
        report("metroBench" in src, "05 exposes window.metroBench")
        for hook in ("origin-input", "destination-input", "mode-time", "mode-transfers", "route-summary", "swap-btn",
                     "data-station-id"):
            report(hook in src, f"05 mentions #{hook}")
    report((sub / "05-frontend-metro" / "NOTES.md").is_file(), "05 NOTES.md exists")

    print("anonymity")
    anonymity_checks(sub, sid)

    print("\nRESULT:", "all format checks passed" if ok else "some checks FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
