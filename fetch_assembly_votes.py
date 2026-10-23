#!/usr/bin/env python3
"""Collect Assembly floor votes from nyassembly.gov (the Open Legislation API has Senate votes
only). Writes data/assembly_votes_<session>.json, keyed by bill number.

A bill's page is fetched only when the bill has passed the Assembly since it was last checked,
so after the first run only new votes are downloaded.

Usage: python3 fetch_assembly_votes.py [session_year]   (default 2025)
"""
import html, json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

SESSION = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "data", f"bills_{SESSION}.json")
OUT = os.path.join(HERE, "data", f"assembly_votes_{SESSION}.json")
UA = "Mozilla/5.0 (compatible; AlbanyBillTracker/1.0; +https://albanybilltracker.org/)"


def page(print_no):
    """The Assembly's floor-vote page for a bill, e.g. S04574."""
    bn = print_no[0] + print_no[1:].zfill(5)
    url = f"https://nyassembly.gov/leg/?default_fld=&leg_video=&bn={bn}&term={SESSION}&Floor%26nbspVotes=Y"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8", "replace")
            time.sleep(1)  # be gentle with the Assembly's site
            return text
        except Exception as e:
            time.sleep(3 * (attempt + 1))
            err = e
    raise RuntimeError(f"{bn}: {err}")


def parse(text):
    """Each floor vote: date, yea/nay totals, and every member who didn't vote yes."""
    votes = []
    for block in text.split("<caption")[1:]:
        date = re.search(r"DATE:</span><span[^>]*>(\d\d)/(\d\d)/(\d{4})", block)
        tally = re.search(r"YEA/NAY:\s*(\d+)/(\d+)", block)
        if not date or not tally:
            continue
        body = block.split("</caption>", 1)[1].split("<caption", 1)[0]
        members = re.findall(r"<div class='vote' >\s*([^<]*?)\s*</div><div class='name'>\s*([^<]*?)\s*</div>", body)
        votes.append({
            "date": f"{date.group(3)}-{date.group(1)}-{date.group(2)}",
            "yea": int(tally.group(1)),
            "nay": int(tally.group(2)),
            # Votes are "Yes", "No", "ER" (excused) and the like; a trailing mark is a footnote.
            "notYes": [[html.unescape(n), re.sub(r"[^A-Za-z]", "", html.unescape(v))]
                       for v, n in members if not html.unescape(v).startswith("Yes")],
        })
    return votes


def main():
    bills = json.load(open(SRC))["bills"]
    cache = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = []
    for b in bills:
        if b["resolution"]:
            continue
        passed = sorted(a["date"] for a in b["actions"] if a["text"] in ("PASSED ASSEMBLY", "REPASSED ASSEMBLY"))
        if not passed:
            continue
        have = cache.get(b["printNo"], {})
        if have.get("passed") != passed[-1]:
            todo.append((b["printNo"], passed[-1]))
    print(f"{len(todo)} bills to check ({len(cache)} cached)", file=sys.stderr)

    def work(item):
        print_no, passed = item
        try:
            return print_no, {"passed": passed, "votes": parse(page(print_no))}
        except Exception as e:
            print(f"  {e}", file=sys.stderr)
            return print_no, None

    done = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        for print_no, result in pool.map(work, todo):
            if result is not None:
                cache[print_no] = result
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(todo)}", file=sys.stderr)
                json.dump(cache, open(OUT, "w"), separators=(",", ":"))
    json.dump(cache, open(OUT, "w"), separators=(",", ":"), sort_keys=True)
    with_votes = sum(1 for v in cache.values() if v["votes"])
    print(f"{len(cache)} bills, {with_votes} with Assembly floor votes -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
