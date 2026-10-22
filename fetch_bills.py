#!/usr/bin/env python3
"""Download every bill in a NY legislative session from the Senate Open Legislation API
and save a slimmed copy (no full text or memos) to data/bills_<session>.json.

Usage: python3 fetch_bills.py [session_year]   (default 2025, i.e. the 2025-26 session)
API key comes from the NYSENATE_API_KEY environment variable, or else ~/.nysenate_api_key.
"""
import json, os, sys, time, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

SESSION = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
KEY = os.environ.get("NYSENATE_API_KEY") or open(os.path.expanduser("~/.nysenate_api_key")).read().strip()
BASE = f"https://legislation.nysenate.gov/api/3/bills/{SESSION}"
PAGE = 200
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"bills_{SESSION}.json")


def get(offset):
    q = urllib.parse.urlencode({"key": KEY, "limit": PAGE, "offset": offset, "full": "true"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(f"{BASE}?{q}", timeout=180) as r:
                return json.load(r)
        except Exception as e:
            print(f"  retry {attempt + 1} at offset {offset}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"failed at offset {offset}")


def items(x):
    return (x or {}).get("items") or []


def slim(b):
    ver = b.get("activeVersion") or ""
    am = (b.get("amendments") or {}).get("items", {}).get(ver) or {}
    sp = b.get("sponsor") or {}
    mem = sp.get("member") or {}
    st = b.get("status") or {}
    return {
        "printNo": b["basePrintNo"],
        "activeVersion": ver,
        "chamber": (b.get("billType") or {}).get("chamber"),
        "resolution": (b.get("billType") or {}).get("resolution"),
        "title": b.get("title"),
        "summary": b.get("summary"),
        "sponsor": mem.get("fullName"),
        "sponsorShort": mem.get("shortName"),
        "district": mem.get("districtCode"),
        "budget": sp.get("budget"),
        "rules": sp.get("rules"),
        "programInfo": b.get("programInfo"),
        "signed": b.get("signed"),
        "vetoed": b.get("vetoed"),
        "adopted": b.get("adopted"),
        "status": {k: st.get(k) for k in ("statusType", "statusDesc", "actionDate", "committeeName", "billCalNo")},
        "milestones": [{"type": m["statusType"], "date": m["actionDate"]} for m in items(b.get("milestones"))],
        "actions": [{"date": a["date"], "chamber": a["chamber"], "text": a["text"]} for a in items(b.get("actions"))],
        "pastCommittees": [{"chamber": c["chamber"], "name": c["name"], "date": c["referenceDate"]} for c in items(b.get("pastCommittees"))],
        "sameAs": [s["basePrintNo"] for s in items(am.get("sameAs"))],
        "substitutedBy": (b.get("substitutedBy") or {}).get("basePrintNo"),
        "lawSection": am.get("lawSection"),
        "lawCode": am.get("lawCode"),
        "actClause": am.get("actClause"),
        "relatedLaws": {k: v.get("items", []) for k, v in ((am.get("relatedLaws") or {}).get("items") or {}).items()},
        "cosponsorCount": len(items(am.get("coSponsors"))),
        "coSponsors": [m["fullName"] for m in items(am.get("coSponsors"))],
        "multiSponsors": [m["fullName"] for m in items(am.get("multiSponsors"))],
        "publishDate": am.get("publishDate"),
        # Senate votes (floor and committee). The API has no Assembly votes; see fetch_assembly_votes.py.
        "votes": [{
            "type": v.get("voteType"),
            "date": v.get("voteDate"),
            "committee": (v.get("committee") or {}).get("name"),
            "printNo": (v.get("billId") or {}).get("printNo"),
            "counts": {k: g.get("size", 0) for k, g in ((v.get("memberVotes") or {}).get("items") or {}).items()},
            "notYes": [[m.get("fullName"), m.get("districtCode"), k]
                       for k, g in ((v.get("memberVotes") or {}).get("items") or {}).items()
                       if k not in ("AYE", "AYEWR") for m in (g.get("items") or [])],
        } for v in items(b.get("votes"))],
        "previousVersions": [{"session": p["session"], "printNo": p["basePrintNo"]} for p in items(b.get("previousVersions"))],
    }


def main():
    first = get(1)
    total = first["total"]
    if total == 0:
        # A new session before its first bills are filed: keep the previous session as current.
        print(f"No bills yet in the {SESSION} session; nothing written.", file=sys.stderr)
        return
    out = [slim(b) for b in first["result"]["items"]]
    print(f"{total} bills in {SESSION} session", file=sys.stderr)
    offset = 1 + PAGE
    while offset <= total:
        d = get(offset)
        out += [slim(b) for b in d["result"]["items"]]
        print(f"  {len(out)}/{total}", file=sys.stderr)
        offset += PAGE
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"session": SESSION, "fetched": datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET"), "bills": out}, f)
    os.replace(tmp, OUT)
    print(f"wrote {len(out)} bills to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
