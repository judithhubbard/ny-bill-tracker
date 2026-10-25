#!/usr/bin/env python3
"""Collect who to contact about a bill: committee chairs and members in both houses, and the
address of each legislator's official page. Writes data/contacts_<session>.json.

Senate committees, chairs, members and meeting times come from the Open Legislation API.
The Assembly isn't in the API, so its committee chairs and members, and its members' page
addresses, are read from nyassembly.gov. Senators' pages on nysenate.gov can't be fetched
by a script, so their addresses come from SENATE_SLUGS below (checked October 2026), with a
name-based guess for anyone not listed.

Email addresses and official page links for every current legislator come from Open States
(https://data.openstates.org/people/current/ny.csv), keyed by house and district; district
office phones come from the Open States person files, which list every office.

If a source can't be reached, the previous contacts file is kept as is.

Usage: python3 fetch_contacts.py [session_year]   (default 2025)
"""
import csv, html, io, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
# Set in main(), so build_data.py can import the name helpers without an API key.
SESSION = KEY = OUT = None
UA = "Mozilla/5.0 (compatible; AlbanyBillTracker/1.0; +https://albanybilltracker.org/)"

# nysenate.gov page addresses, keyed by first + last name (see name_key).
SENATE_SLUGS = {
    "joseph addabbo": "joseph-p-addabbo-jr", "jacob ashby": "jacob-ashby", "jamaal bailey": "jamaal-t-bailey",
    "april baskin": "april-baskin", "george borrello": "george-m-borrello", "erik bottcher": "erik-bottcher",
    "jabari brisport": "jabari-brisport", "samra brouk": "samra-g-brouk", "siela bynoe": "siela-bynoe",
    "patricia canzoneri-fitzpatrick": "patricia-canzoneri-fitzpatrick", "stephen chan": "stephen-t-chan",
    "cordell cleare": "cordell-cleare", "leroy comrie": "leroy-comrie", "jeremy cooney": "jeremy-cooney",
    "patricia fahy": "patricia-fahy", "nathalia fernandez": "nathalia-fernandez",
    "patrick gallivan": "patrick-m-gallivan", "kristen gonzalez": "kristen-gonzalez",
    "andrew gounardes": "andrew-gounardes", "joseph griffo": "joseph-griffo", "pete harckham": "pete-harckham",
    "pamela helming": "pamela-helming", "michelle hinchey": "michelle-hinchey", "robert jackson": "robert-jackson",
    "brian kavanagh": "brian-kavanagh", "liz krueger": "liz-krueger", "andrew lanza": "andrew-j-lanza",
    "john liu": "john-c-liu", "monica martinez": "monica-r-martinez", "jack martins": "jack-m-martins",
    "mario mattera": "mario-r-mattera", "rachel may": "rachel-may", "shelley mayer": "shelley-b-mayer",
    "dean murray": "dean-murray", "zellnor myrie": "zellnor-myrie", "thomas omara": "thomas-f-omara",
    "peter oberacker": "peter-oberacker", "robert ortt": "robert-g-ortt", "anthony palumbo": "anthony-h-palumbo",
    "kevin parker": "kevin-s-parker", "roxanne persaud": "roxanne-j-persaud", "jessica ramos": "jessica-ramos",
    "steven rhoads": "steven-d-rhoads", "gustavo rivera": "gustavo-rivera", "rob rolison": "rob-rolison",
    "christopher ryan": "christopher-j-ryan", "julia salazar": "julia-salazar", "james sanders": "james-sanders-jr",
    "jessica scarcella-spanton": "jessica-scarcella-spanton", "luis sepulveda": "luis-r-sepulveda",
    "jose serrano": "jose-m-serrano", "james skoufis": "james-skoufis", "toby stavisky": "toby-ann-stavisky",
    "daniel stec": "daniel-g-stec", "andrea stewart-cousins": "andrea-stewart-cousins", "sam sutton": "sam-sutton",
    "james tedisco": "james-tedisco", "mark walczyk": "mark-walczyk", "lea webb": "lea-webb",
    "bill weber": "bill-weber", "alexis weik": "alexis-weik", "jeremy zellner": "jeremy-j-zellner",
}


def name_key(name):
    """'Thomas F. O'Mara' and 'Thomas O'Mara' -> 'thomas omara'; drops middle names and suffixes."""
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    n = re.sub(r"^(mr|mrs|ms|dr)\.?\s+", "", n)
    words = [w for w in re.sub(r"[^a-z\s-]", "", n).split() if w not in ("jr", "sr", "ii", "iii", "iv")]
    return f"{words[0]} {words[-1]}" if len(words) > 1 else (words[0] if words else "")


def committee_key(name):
    return re.sub(r"[^a-z]", "", (name or "").lower().replace("and", ""))


def senate_url(name):
    slug = SENATE_SLUGS.get(name_key(name))
    if not slug:
        n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"['.]", "", n)).strip("-")
    return f"https://www.nysenate.gov/senators/{slug}"


def get(url, as_json=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
                return json.loads(body) if as_json else body
        except Exception as e:
            print(f"  retry {attempt + 1}: {url.split('?')[0]}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url.split('?')[0]}")


def meeting_text(c):
    day, tm, loc = c.get("meetDay"), c.get("meetTime"), c.get("location")
    if not day:
        return None
    when = day.title() + "s"
    if tm:
        h, m = map(int, tm.split(":")[:2])
        when += f" at {h % 12 or 12}:{m:02d} {'a.m.' if h < 12 else 'p.m.'}"
    if c.get("meetAltWeek"):
        when += f" ({c.get('meetAltWeekText') or 'alternate weeks'})"
    if loc:
        loc = re.sub(r"\bCAP\b", "Capitol", re.sub(r"\bLOB\b", "Legislative Office Building", loc))
    return f"{when}, {loc}" if loc else when


def senate():
    q = urllib.parse.urlencode({"key": KEY, "full": "true", "limit": 100})
    d = get(f"https://legislation.nysenate.gov/api/3/committees/{SESSION}/senate?{q}", as_json=True)
    committees = {}
    if not d["result"]["items"]:
        raise RuntimeError("no committees listed for this session yet")
    for c in d["result"]["items"]:
        members = c.get("committeeMembers", {}).get("items", [])
        chair = next((m["fullName"] for m in members if m.get("title") == "CHAIR_PERSON"), None)
        committees[committee_key(c["name"])] = {
            "name": c["name"],
            "chair": chair,
            "members": [m["fullName"] for m in members],
            "meets": meeting_text(c),
        }
    return committees


def assembly():
    listing = get("https://nyassembly.gov/comm/")
    committees = {}
    for m in re.finditer(r'<div class="comm-title"><a href="\?id=(\d+)">([^<]+)</a></div>(.*?)</li>', listing, re.S):
        cid, name, block = m.group(1), html.unescape(m.group(2)).strip(), m.group(3)
        chair = re.search(r'Chair</strong>.*?<a href="/mem/([^"]+)">\s*([^<]+)</a>', block, re.S)
        page = get(f"https://nyassembly.gov/comm/?id={cid}&sec=mem")
        members = sorted({(s, html.unescape(n).strip()) for s, n in re.findall(r'<a href="/mem/([A-Za-z0-9.-]+)"><img[^>]*?title="\s*([^"]+?)\s*"', page)})
        committees[committee_key(name)] = {
            "name": name,
            "chair": html.unescape(chair.group(2)).strip() if chair else None,
            "members": [n for _, n in members],
            "url": f"https://nyassembly.gov/comm/?id={cid}",
        }
        time.sleep(0.5)
    if len(committees) < 20:
        raise RuntimeError(f"only {len(committees)} Assembly committees found; page layout may have changed")
    roster = get("https://nyassembly.gov/mem/")
    members = {}
    for block in roster.split('class="mem-name"')[1:]:
        m = re.search(r'href="/mem/([A-Za-z0-9.-]+)">\s*([^<]+?)\s*<span>District (\d+)', block)
        if not m:
            continue
        email = re.search(r'mailto:([^"]+)"', block[:1500])
        members[name_key(html.unescape(m.group(2)))] = {
            "url": f"https://nyassembly.gov/mem/{m.group(1)}",
            "district": int(m.group(3)),
            "email": email.group(1) if email else None,
        }
    if len(members) < 100:
        raise RuntimeError(f"only {len(members)} Assembly members found; page layout may have changed")
    return committees, members


def district_offices():
    """Every district office with a phone, main office first: {"S:52": [["Binghamton",
    "607-773-8771"], ["Ithaca", "607-878-7025"]]}. From the Open States person files, which
    list all offices (the spreadsheet has only one phone). Empty if they can't be read."""
    import subprocess, tempfile
    root = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/openstates/people.git", root], check=True, timeout=300)
        subprocess.run(["git", "-C", root, "sparse-checkout", "set", "data/ny/legislature"], check=True, timeout=300)
    except Exception as e:
        print(f"Open States offices: {e}", file=sys.stderr)
        return {}
    out = {}
    folder = os.path.join(root, "data", "ny", "legislature")
    for fn in os.listdir(folder):
        section, item, items, seat, last_key = None, None, {"roles": [], "offices": []}, None, None
        for line in open(os.path.join(folder, fn), encoding="utf-8"):
            line = line.rstrip("\n")
            m = re.match(r"^(\w+):", line)
            if m:
                section, item = m.group(1), None
                continue
            m = re.match(r"^(- |  )(\w+):\s*(.*)$", line)
            if m and section in items:
                if m.group(1) == "- ":
                    item = {}
                    items[section].append(item)
                item[m.group(2)] = m.group(3).strip("'\"")
                last_key = m.group(2)
            elif item is not None and line.startswith("    ") and last_key:
                item[last_key] += " " + line.strip()  # a long value wrapped onto the next line
        role = next((r for r in items["roles"] if not r.get("end_date") and r.get("district", "").isdigit()), None)
        if not role or role.get("type") not in ("upper", "lower"):
            continue
        seat = ("S" if role["type"] == "upper" else "A") + ":" + str(int(role["district"]))
        phones = []
        for o in items["offices"]:
            if o.get("classification") == "district" and o.get("voice"):
                city = re.search(r",\s*([^,]+?),\s*NY\b", o.get("address", ""))
                phones.append([city.group(1).strip() if city else "", o["voice"]])
        if phones:
            out[seat] = phones
    return out


def people():
    """Every current legislator: {"S:52": {...}, "A:125": {...}} from Open States."""
    text = get("https://data.openstates.org/people/current/ny.csv")
    offices = district_offices()
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        house = {"upper": "S", "lower": "A"}.get(r["current_chamber"])
        if not house or not r["current_district"].isdigit():
            continue
        links = [l for l in r["links"].split(";") if re.search(r"nysenate\.gov/senators/|nyassembly\.gov/mem/", l)]
        seat = f"{house}:{int(r['current_district'])}"
        phone = r["district_voice"] or r["capitol_voice"] or None
        phones = offices.get(seat) or ([["", phone]] if phone else [])
        out[seat] = {
            "name": r["name"],
            "key": name_key(r["name"]),
            "email": r["email"] or None,
            # The main district office first; "phones" lists every district office.
            "phone": phones[0][1] if phones else None,
            "phones": phones,
            "url": links[0] if links else None,
            "party": r["current_party"] or None,
            "image": r["image"] or None,
        }
    if len(out) < 200:
        raise RuntimeError(f"only {len(out)} legislators found")
    return out


def service():
    """First session year each sitting member served in their current house: {"A:125": 2021}.
    The API's records start in 2009."""
    out = {}
    for chamber, house in (("senate", "S"), ("assembly", "A")):
        q = urllib.parse.urlencode({"key": KEY, "full": "true", "limit": 300})
        d = get(f"https://legislation.nysenate.gov/api/3/members/{SESSION}/{chamber}?{q}", as_json=True)
        for m in d["result"]["items"]:
            years = (m.get("service") or {}).get("sessionYearsServed") or []
            if m.get("districtCode") and years and m.get("incumbent"):
                out[f"{house}:{m['districtCode']}"] = min(years)
    return out


def main():
    global SESSION, KEY, OUT
    SESSION = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    KEY = os.environ.get("NYSENATE_API_KEY") or open(os.path.expanduser("~/.nysenate_api_key")).read().strip()
    OUT = os.path.join(HERE, "data", f"contacts_{SESSION}.json")
    # A new session starts from the last one's file: early in January the API has no committees
    # for the new session yet, so the Senate committees are carried over until it does.
    prev = os.path.join(HERE, "data", f"contacts_{SESSION - 2}.json")
    old = json.load(open(OUT)) if os.path.exists(OUT) else json.load(open(prev)) if os.path.exists(prev) else {}
    out = {"session": SESSION, "fetched": datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d"), "kept": {}}

    def keep(part):
        """A source failed: note how old the copy kept instead is (check_fresh.py reports it)."""
        out["kept"][part] = old.get("kept", {}).get(part) or {"session": old.get("session"), "fetched": old.get("fetched")}
    try:
        out["senateCommittees"] = senate()
    except Exception as e:
        print(f"Senate committees: {e}; keeping previous", file=sys.stderr)
        out["senateCommittees"] = old.get("senateCommittees", {})
        keep("Senate committees")
    try:
        out["people"] = people()
    except Exception as e:
        print(f"Open States: {e}; keeping previous", file=sys.stderr)
        out["people"] = old.get("people", {})
        keep("Legislator contacts")
    try:
        out["since"] = service()
    except Exception as e:
        print(f"Service years: {e}; keeping previous", file=sys.stderr)
        out["since"] = old.get("since", {})
    try:
        out["assemblyCommittees"], out["assemblyMembers"] = assembly()
    except Exception as e:
        print(f"Assembly: {e}; keeping previous", file=sys.stderr)
        out["assemblyCommittees"] = old.get("assemblyCommittees", {})
        out["assemblyMembers"] = old.get("assemblyMembers", {})
        keep("Assembly committees")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(f"{len(out['people'])} legislators, {len(out['senateCommittees'])} Senate committees, {len(out['assemblyCommittees'])} Assembly committees, "
          f"{len(out['assemblyMembers'])} Assembly members -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
