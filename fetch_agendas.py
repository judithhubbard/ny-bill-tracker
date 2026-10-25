#!/usr/bin/env python3
"""Committee meeting agendas for a session: which bills each committee will take up, and when.
Senate agendas come from the Open Legislation API; Assembly agendas from the committee agenda
pages on nyassembly.gov, which list upcoming meetings only. Writes data/agendas_<session>.json:
{"S1234": [["Senate Health", "2026-01-20T10:30:00"], ...]} keyed by bill number without
amendment letter.

Usage: python3 fetch_agendas.py [session_year]   (default 2025)
API key from NYSENATE_API_KEY, or else ~/.nysenate_api_key."""
import datetime, html, json, os, re, sys, time, urllib.parse, urllib.request

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


ASM = "https://nyassembly.gov/leg/"


def page(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; AlbanyBillTracker/1.0; +https://albanybilltracker.org/)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  retry {attempt + 1} for {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    return ""


def problem(text):
    """Notes a problem for the build's freshness check (the workflow sets PROBLEMS_FILE)."""
    print(text, file=sys.stderr)
    # Committees meet January to June; outside that, an empty agenda page is normal.
    if os.environ.get("PROBLEMS_FILE") and datetime.date.today().month <= 6:
        with open(os.environ["PROBLEMS_FILE"], "a") as f:
            f.write(text + "\n")


def assembly(out):
    """Upcoming Assembly committee meetings: the agenda list links to one page per meeting, whose
    header gives committee, time and room, followed by the bills it will take up."""
    links = re.findall(r'href="(\?sh=agen2[^"]+)"', page(ASM + "?sh=agen"))
    n = 0
    for link in dict.fromkeys(html.unescape(l) for l in links):
        com = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("com", [""])[0].strip()
        body = page(ASM + link.replace(" ", "%20"))
        m = re.search(r"(\d{1,2}:\d{2} [AP]M), \w+ (\w+ \d{1,2}), ?(\d{4})", body)
        if not (com and m):
            continue
        when = datetime.datetime.strptime(f"{m[2]} {m[3]} {m[1]}", "%B %d %Y %I:%M %p").isoformat()
        table = body[body.find("<table"):body.rfind("</table>")]
        # Bill numbers from links to bill pages, or failing that from the table's text.
        text = " ".join(re.findall(r"bn=([AS]\d+)", table)) or html.unescape(re.sub(r"<[^>]+>", " ", table))
        for h, num in re.findall(r"\b([AS])0*(\d{1,5})[A-Z]?\b", text):
            entry = [f"Assembly {com}", when]
            if entry not in out.setdefault(h + num, []):
                out[h + num].append(entry)
                n += 1
    print(f"Assembly: {len(links)} meetings, {n} bill listings", file=sys.stderr)
    # Meetings listed but no bills read from them: the page layout has probably changed.
    if links and not n:
        problem(f"The Assembly agenda page lists {len(set(links))} meetings, but no bills could be read from them. Its layout may have changed (fetch_agendas.py).")


def main():
    session = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    key = os.environ.get("NYSENATE_API_KEY") or open(os.path.expanduser("~/.nysenate_api_key")).read().strip()
    out = {}
    for year in (session, session + 1):
        for ag in get(f"agendas/{year}", key)["items"]:
            detail = get(f"agendas/{year}/{ag['id']['number']}", key)
            for c in (detail.get("committeeAgendas") or {}).get("items", []):
                name = "Senate " + c["committeeId"]["name"]
                for add in (c.get("addenda") or {}).get("items", []):
                    when = (add.get("meeting") or {}).get("meetingDateTime")
                    for b in (add.get("bills") or {}).get("items", []):
                        p = b["billId"]["basePrintNo"] if "basePrintNo" in b["billId"] else b["billId"]["printNo"].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                        entry = [name, when]
                        if when and entry not in out.setdefault(p, []):
                            out[p].append(entry)
    try:
        assembly(out)
    except Exception as e:
        problem(f"Assembly committee agendas didn't download: {e}")
    path = os.path.join(HERE, "data", f"agendas_{session}.json")
    with open(path, "w") as f:
        json.dump(out, f, sort_keys=True)
    print(f"{sum(map(len, out.values()))} agenda listings for {len(out)} bills -> {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
