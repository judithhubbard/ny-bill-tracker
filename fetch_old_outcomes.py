#!/usr/bin/env python3
"""How far each bill got in sessions older than the full downloads (2007-2015), so a bill's
history can show earlier outcomes instead of just "introduced". Uses the API's short list
view (status and milestones only). Writes data/old_outcomes.json.gz:
{session: {basePrintNo: code}}, code = stage * 4 + 1 if passed Senate + 2 if passed Assembly.
These sessions are closed, so a session already in the file is skipped.

Usage: python3 fetch_old_outcomes.py [first_session last_session]   (default 2007 2015)"""
import gzip, json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "old_outcomes.json.gz")
KEY = os.environ.get("NYSENATE_API_KEY") or open(os.path.expanduser("~/.nysenate_api_key")).read().strip()
PAGE = 1000


def get(session, offset):
    q = urllib.parse.urlencode({"key": KEY, "limit": PAGE, "offset": offset})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(f"https://legislation.nysenate.gov/api/3/bills/{session}?{q}", timeout=180) as r:
                return json.load(r)
        except Exception as e:
            print(f"  retry {attempt + 1} at {session}/{offset}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"failed at {session}/{offset}")


def code(b):
    ms = {m["statusType"] for m in (b.get("milestones") or {}).get("items", [])}
    ps, pa = "PASSED_SENATE" in ms, "PASSED_ASSEMBLY" in ms
    if b["signed"] or "SIGNED_BY_GOV" in ms:
        stage = 5
    elif b["vetoed"] or "VETOED" in ms:
        stage = 6
    elif "DELIVERED_TO_GOV" in ms:
        stage = 4
    elif ps and pa:
        stage = 3
    elif ps or pa:
        stage = 2
    else:
        stage = 0
    return stage * 4 + ps + 2 * pa


def main():
    first, last = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (2007, 2015)
    data = json.load(gzip.open(OUT, "rt")) if os.path.exists(OUT) else {}
    for s in range(first, last + 1, 2):
        if str(s) in data:
            continue
        out, offset, total = {}, 1, None
        while total is None or offset <= total:
            d = get(s, offset)
            total = d["total"]
            for b in d["result"]["items"]:
                if not b["billType"]["resolution"]:
                    out[b["basePrintNo"]] = code(b)
            offset += PAGE
        data[str(s)] = out
        print(f"{s}: {len(out)} bills")
    with gzip.open(OUT, "wt") as f:
        json.dump(data, f, separators=(",", ":"))


if __name__ == "__main__":
    main()
