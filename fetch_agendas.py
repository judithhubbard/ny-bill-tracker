#!/usr/bin/env python3
"""Senate committee meeting agendas for a session, from the Open Legislation API: which bills
each committee will take up, and when. Writes data/agendas_<session>.json:
{"S1234": [["Health", "2026-01-20T10:30:00"], ...]} keyed by bill number without amendment letter.
The Assembly doesn't publish agendas through the API.

Usage: python3 fetch_agendas.py [session_year]   (default 2025)
API key from NYSENATE_API_KEY, or else ~/.nysenate_api_key."""
import json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def get(path, key):
    q = urllib.parse.urlencode({"key": key, "limit": 1000})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"https://legislation.nysenate.gov/api/3/{path}?{q}", timeout=120) as r:
                return json.load(r)["result"]
        except Exception as e:
            print(f"  retry {attempt + 1} for {path}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"failed: {path}")


def main():
    session = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    key = os.environ.get("NYSENATE_API_KEY") or open(os.path.expanduser("~/.nysenate_api_key")).read().strip()
    out = {}
    for year in (session, session + 1):
        for ag in get(f"agendas/{year}", key)["items"]:
            detail = get(f"agendas/{year}/{ag['id']['number']}", key)
            for c in (detail.get("committeeAgendas") or {}).get("items", []):
                name = c["committeeId"]["name"]
                for add in (c.get("addenda") or {}).get("items", []):
                    when = (add.get("meeting") or {}).get("meetingDateTime")
                    for b in (add.get("bills") or {}).get("items", []):
                        p = b["billId"]["basePrintNo"] if "basePrintNo" in b["billId"] else b["billId"]["printNo"].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                        entry = [name, when]
                        if when and entry not in out.setdefault(p, []):
                            out[p].append(entry)
    path = os.path.join(HERE, "data", f"agendas_{session}.json")
    with open(path, "w") as f:
        json.dump(out, f, sort_keys=True)
    print(f"{sum(map(len, out.values()))} agenda listings for {len(out)} bills -> {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
