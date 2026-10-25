#!/usr/bin/env python3
"""Checks that the data behind the site is current, after the daily build.

Several downloads in the build are allowed to fail (the site is built from the last good copy),
so a source that keeps failing would otherwise go unnoticed. This lists anything that looks
behind, writes it to the run's summary, and exits 1 so the workflow is marked failed and
GitHub emails the owner. The site is deployed either way.

Usage: python3 check_fresh.py SESSION [PROBLEMS_FILE]
  PROBLEMS_FILE: lines written by build steps that failed (optional).
"""
import json, os, sys
from datetime import datetime, timedelta, timezone

SESSION = int(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
data = lambda name: os.path.join(HERE, "data", name)
now = datetime.now(timezone(timedelta(hours=-5)))  # Eastern standard time is close enough for day counts
problems = []

# Steps that failed in this run (written by the workflow).
if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
    problems += [l.strip() for l in open(sys.argv[2]) if l.strip()]

# Bills from Open Legislation: downloaded on every run. A new session has no file until its first
# bills are filed (prefiled bills usually appear in December); until then the last one stays current.
if not os.path.exists(data(f"bills_{SESSION}.json")):
    if (now.month, now.day) > (1, 15):
        problems.append(f"No bills have been downloaded for the {SESSION} session yet.")
    report = ("## Data is behind\n\n" + "\n".join(f"- {p}" for p in problems)) if problems else f"## No {SESSION} bills yet"
    print(report)
    sys.exit(1 if problems else 0)
bills = json.load(open(data(f"bills_{SESSION}.json")))
fetched = datetime.strptime(bills["fetched"][:10], "%Y-%m-%d").date()
if (now.date() - fetched).days >= 2:
    problems.append(f"Bill data was last downloaded {fetched}.")

# Assembly floor votes: every bill that passed the Assembly should have its vote collected.
votes = json.load(open(data(f"assembly_votes_{SESSION}.json"))) if os.path.exists(data(f"assembly_votes_{SESSION}.json")) else {}
missing = []
for b in bills["bills"]:
    if b.get("resolution"):
        continue
    passed = sorted(a["date"] for a in b["actions"] if a["text"] in ("PASSED ASSEMBLY", "REPASSED ASSEMBLY"))
    if passed and votes.get(b["printNo"], {}).get("passed") != passed[-1]:
        missing.append(b["printNo"])
if len(missing) > 10:
    problems.append(f"{len(missing)} bills passed the Assembly but their votes haven't been collected (e.g. {', '.join(missing[:5])}).")

# Committee assignments and contacts: refreshed daily, but they rarely change, so allow two weeks.
cpath = data(f"contacts_{SESSION}.json")
if os.path.exists(cpath):
    c = json.load(open(cpath)).get("fetched", "")[:10]
    if c and (now.date() - datetime.strptime(c, "%Y-%m-%d").date()).days > 14:
        problems.append(f"Legislator contacts and committees were last refreshed {c}.")

report = ("## Data is behind\n\n" + "\n".join(f"- {p}" for p in problems)) if problems else "## Data is current"
print(report)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
        f.write(report + "\n")
sys.exit(1 if problems else 0)
