#!/usr/bin/env python3
"""Turn data/bills_<session>.json files (from fetch_bills.py) into tracker pages,
site/<session>.html: tracker.html with that session's bill data embedded in it.

Pairs Senate and Assembly versions of the same bill, works out how far each pair got,
tags each pair with topics based on committees and the laws it amends, and links each
bill to its versions in earlier and later sessions (the API's "previous versions").

Usage: python3 build_data.py            builds every session found in data/
       python3 build_data.py 2025       builds just that session's page (still reads
                                        the other sessions for bill histories)
       python3 build_data.py --github _site
                                        builds the GitHub Pages version into _site/:
                                        index.html for the current session, <year>.html
                                        for the others, linked to each other
"""
import glob, gzip, json, os, re, sys
from fetch_contacts import committee_key, name_key, senate_url
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "tracker.html")
SITE = os.path.join(HERE, "site")
# Published URL of each session's page, filled in after the first publish of each.
URLS_FILE = os.path.join(HERE, "artifact_urls.json")
# Session data may be plain JSON (fresh downloads) or gzipped (past sessions kept in git).
SESSIONS = sorted({int(re.search(r"bills_(\d{4})", f).group(1)) for f in glob.glob(os.path.join(HERE, "data", "bills_*.json*"))})
ARGS = sys.argv[1:]
GITHUB = None
if "--github" in ARGS:
    i = ARGS.index("--github")
    GITHUB = os.path.abspath(ARGS[i + 1])
    del ARGS[i:i + 2]
ONLY = [int(a) for a in ARGS] or SESSIONS
# The GitHub Pages address, used for share links and links to single bills.
SITE_URL = os.environ.get("SITE_URL", "https://judithhubbard.github.io/ny-bill-tracker/")


def read_session(session):
    path = os.path.join(HERE, "data", f"bills_{session}.json")
    if os.path.exists(path):
        return json.load(open(path))
    with gzip.open(path + ".gz", "rt") as f:
        return json.load(f)

# Sponsor checkboxes: only Sen. Webb (SD 52, from 2023) and Asm. Kelles (AD 125, from 2021).
# Later sessions use the same districts, but a checkbox appears only while Webb or Kelles
# holds the seat. Sessions with neither get no checkboxes.
DELEGATION = {
    2021: {"ASSEMBLY": {125}},
}
DEFAULT_DELEGATION = {"SENATE": {52}, "ASSEMBLY": {125}}  # 2023 onward
DELEGATION_NAMES = {"Webb", "Kelles"}

# Who decides which bills reach each house's floor. Check after leadership votes in January
# of odd years; a leader is shown only while the named person still holds a seat.
LEADERS = {"S": ("Andrea Stewart-Cousins", "Senate Majority Leader"),
           "A": ("Carl Heastie", "Assembly Speaker")}


def delegation(session):
    return DELEGATION.get(session, DEFAULT_DELEGATION if session >= 2023 else {})

# Topic: (label, committees, laws amended, title/summary words).
# Committee and law names are matched exactly as the API spells them.
TOPICS = {
    "env": ("Environment & energy",
            {"Environmental Conservation", "Energy", "Energy And Telecommunications"},
            {"Environmental Conservation Law", "Environmental Conservation", "Navigation Law",
             "Energy Law", "Energy"},
            r"\b(climate|greenhouse|emission|renewable|solar|wind energy|pollut\w*|wetland|watershed|"
            r"drinking water|pesticide|plastic|recycl\w*|pfas|stormwater|wastewater|invasive species|"
            r"conservation easement|forest|wildlife|clean water|clean air|composting|landfill)\b"),
    "local": ("Local government",
              {"Local Government", "Local Governments", "Cities", "Cities 1", "Cities 2"},
              {"County Law", "Town Law", "Village Law", "General Municipal Law", "Municipal Home Rule Law",
               "Local Finance Law", "General City Law"},
              None),
    "tax": ("Taxes & assessment",
            {"Budget And Revenue", "Real Property Taxation"},
            {"Tax Law", "Real Property Tax Law", "Real Property Taxation", "Taxation"},
            None),
    "safety": ("Public safety & courts",
               {"Codes", "Correction", "Crime Victims, Crime And Correction", "Judiciary"},
               {"Penal Law", "Criminal Procedure Law", "Correction Law", "Family Court Act", "Judiciary Law",
                "Civil Practice Law and Rules", "Court of Claims Act"},
               None),
    "human": ("Human services",
              {"Social Services", "Children And Families", "Aging", "Disabilities", "People With Disabilities",
               "Women's Issues", "Veterans, Homeland Security And Military Affairs", "Veterans' Affairs"},
              {"Social Services Law", "Social Services", "Elder Law", "Veterans' Service Law"},
              None),
    "health": ("Health & mental health",
               {"Health", "Mental Health", "Mental Health And Developmental Disabilities", "Alcoholism And Drug Abuse",
                "Alcoholism And Substance Use Disorders", "Alcoholism And Substance Abuse"},
               {"Public Health Law", "Public Health", "Mental Hygiene Law", "Mental Hygiene"},
               None),
    "edu": ("Education",
            {"Education", "Higher Education", "Libraries", "Libraries And Education Technology",
             "New York City Education"},
            {"Education Law", "Education"},
            None),
    "transp": ("Transportation & highways",
               {"Transportation", "Infrastructure And Capital Investment"},
               {"Vehicle and Traffic Law", "Highway Law", "Transportation Law", "Transportation"},
               None),
    "labor": ("Labor & public employees",
              {"Labor", "Governmental Employees", "Civil Service And Pensions"},
              {"Labor Law", "Civil Service Law", "Civil Service", "Retirement and Social Security Law",
               "Retirement", "Workers' Compensation Law"},
              None),
    "housing": ("Housing",
                {"Housing", "Housing, Construction And Community Development"},
                {"Real Property Law", "Private Housing Finance Law", "Public Housing Law", "Multiple Dwelling Law",
                 "Real Property Actions and Proceedings Law", "Emergency Tenant Protection Act of 1974"},
                None),
    "ag": ("Agriculture",
           {"Agriculture", "Domestic Animal Welfare"},
           {"Agriculture and Markets Law"},
           None),
    "gov": ("Elections & state government",
            {"Election Law", "Elections", "Governmental Operations", "Investigations And Government Operations",
             "Ethics And Internal Governance", "Procurement And Contracts"},
            {"Election Law", "Public Officers Law", "Legislative Law", "State Finance Law"},
            None),
    "biz": ("Business & consumers",
            {"Consumer Affairs And Protection", "Consumer Protection", "Banks", "Insurance", "Economic Development",
             "Commerce, Economic Development And Small Business", "Small Business",
             "Corporations, Authorities And Commissions", "Racing And Wagering", "Racing, Gaming And Wagering",
             "Internet And Technology", "Science And Technology"},
            {"General Business Law", "Insurance Law", "Banking Law", "Financial Services Law",
             "Alcoholic Beverage Control Law", "Cannabis Law"},
            None),
    "const": ("Constitutional amendments", set(), {"Constitution, Concurrent Resolutions to Amend"}, None),
}
TOPIC_WORDS = {k: re.compile(v[3], re.I) for k, v in TOPICS.items() if v[3]}

# Laws that touch county and municipal operations, for the "local government impact" filter.
LOCAL_LAWS = TOPICS["local"][2] | {"Real Property Tax Law", "Real Property Taxation", "Social Services Law"}
LOCAL_WORDS = re.compile(r"\b(count(y|ies)|municipal\w*|local governments?|unfunded mandate)\b", re.I)

STAGE_LABEL = ["In committee", "On the floor", "Passed one house", "Passed both houses",
               "Delivered to governor", "Signed into law", "Vetoed"]


def norm_comm(name):
    return "Rules" if name.startswith("Rules") else name


def bill_stage(b):
    """How far this one version got, 0-6 (6 = vetoed)."""
    ms = {m["type"] for m in b["milestones"]}
    if b["signed"] or "SIGNED_BY_GOV" in ms:
        return 5
    if b["vetoed"] or "VETOED" in ms:
        return 6
    if "DELIVERED_TO_GOV" in ms:
        return 4
    if {"PASSED_SENATE", "PASSED_ASSEMBLY"} <= ms:
        return 3
    if ms & {"PASSED_SENATE", "PASSED_ASSEMBLY"}:
        return 2
    if ms & {"SENATE_FLOOR", "ASSEMBLY_FLOOR"}:
        return 1
    return 0


def rank(stage):
    # Vetoed sits after delivered but before signed when choosing the furthest version.
    return {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 6: 5, 5: 6}[stage]




SENATE_CODES = {"NAY": "N", "EXC": "E", "ABS": "A", "ABD": "B"}
ASSEMBLY_CODES = {"No": "N", "ER": "E", "Abs": "A", "Abstain": "B", "NV": "A"}


def collect_votes(live, avotes):
    """Senate votes (API) and Assembly floor votes (nyassembly.gov) for a bill's versions.
    Each: [house, "F"/"C", committee, date, yes, no, [[member, code], ...]] listing only
    members who didn't vote yes; members are ("S", district) or ("A", short name)."""
    out, seen = [], set()
    for b in live:
        for v in b.get("votes", []):
            key = ("S", v["type"], v["date"], v.get("committee"))
            if key in seen:
                continue
            seen.add(key)
            c = v["counts"]
            out.append(["S", "F" if v["type"] == "FLOOR" else "C", v.get("committee"), v["date"],
                        c.get("AYE", 0) + c.get("AYEWR", 0), c.get("NAY", 0),
                        [[("S", d), SENATE_CODES.get(code, code)] for _, d, code in v["notYes"]]])
        for v in (avotes.get(b["printNo"]) or {}).get("votes", []):
            key = ("A", "F", v["date"], v["yea"], v["nay"])
            if key in seen:
                continue
            seen.add(key)
            out.append(["A", "F", None, v["date"], v["yea"], v["nay"],
                        [[("A", n), ASSEMBLY_CODES.get(code, code)] for n, code in v["notYes"]]])
    return sorted(out, key=lambda v: v[3])


LEFT_COMMITTEE = ("ADVANCED TO THIRD READING", "ORDERED TO THIRD READING", "REPORTED", "COMMITTEE DISCHARGED",
                  "PASSED SENATE", "PASSED ASSEMBLY")


# Committees renamed between sessions, mapped to their current names.
COMMITTEE_RENAMES = {
    "Alcoholism And Substance Abuse": "Alcoholism And Substance Use Disorders",
    "Mental Health And Developmental Disabilities": "Mental Health",
}


def first_committees(live):
    """For each version: the first committee in its own house, and whether the bill got out of it."""
    out = []
    for b in live:
        # The API lists committees by name, not date; the first referral is the earliest.
        own = sorted((c for c in b["pastCommittees"] if c["chamber"] == b["chamber"]), key=lambda c: c.get("date") or "")
        if not own:
            continue
        name = COMMITTEE_RENAMES.get(norm_comm(own[0]["name"]), norm_comm(own[0]["name"]))
        if name in ("Rules", "Calendar"):
            continue
        left = any(a["chamber"] == b["chamber"] and a["text"].startswith(LEFT_COMMITTEE) for a in b["actions"])
        out.append((b["chamber"][0], name, left))
    return out


TITLE_STOP = set("the a an of to and or for in on by with relates relating certain provides requires establishes authorizes".split())


def title_overlap(a, b):
    """Share of the shorter title's words that the other title also uses."""
    wa, wb = ({w for w in re.findall(r"[a-z]+", (x or "").lower()) if w not in TITLE_STOP and len(w) > 2} for x in (a, b))
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def load_session(session):
    """Read one session's bills and return (records, printNo -> record index, fetched time)."""
    raw = read_session(session)
    bills = {b["printNo"]: b for b in raw["bills"] if not b["resolution"]}
    deleg = delegation(session)

    # The API names some laws two ways ("Cannabis" and "Cannabis Law"); use the full name.
    law_names = {b["lawSection"] for b in bills.values() if b["lawSection"]}
    for b in bills.values():
        if b["lawSection"] and b["lawSection"] + " Law" in law_names:
            b["lawSection"] = b["lawSection"] + " Law"

    # Union-find over "same as" and substitution links.
    parent = {p: p for p in bills}

    def find(p):
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    def union(a, b):
        if a in parent and b in parent:
            parent[find(a)] = find(b)

    # The API occasionally points a bill at an unrelated "same as" (S10006 -> A11368, a
    # physical therapy bill). Skip a link when it only goes one way and the titles share
    # almost no words; one-way links between matching titles are ordinary reintroductions.
    for b in bills.values():
        for s in b["sameAs"]:
            back = bills[s]["sameAs"] if s in bills else []
            if back and b["printNo"] not in back and title_overlap(b["title"], bills[s]["title"]) < 0.25:
                continue
            union(b["printNo"], s)
        if b["substitutedBy"]:
            union(b["printNo"], b["substitutedBy"])

    groups = {}
    for p in bills:
        groups.setdefault(find(p), []).append(bills[p])

    avotes_path = os.path.join(HERE, "data", f"assembly_votes_{session}.json")
    avotes = json.load(open(avotes_path)) if os.path.exists(avotes_path) else {}
    recs, index = [], {}
    for members in groups.values():
        live = [b for b in members if b["status"]["statusType"] != "STRICKEN"]
        if not live:
            continue
        for b in live:
            b["_stage"] = bill_stage(b)
        live.sort(key=lambda b: (-rank(b["_stage"]), b["chamber"] != "SENATE", b["printNo"]))
        lead = live[0]

        ms = {m["type"] for b in live for m in b["milestones"]}
        stage = max((b["_stage"] for b in live), key=rank)
        if stage < 3 and {"PASSED_SENATE", "PASSED_ASSEMBLY"} <= ms:
            stage = 3
        passed_in = None
        if stage == 2:
            passed_in = "Senate" if "PASSED_SENATE" in ms else "Assembly"

        chapter = veto = None
        for b in live:
            for a in b["actions"]:
                m = re.match(r"SIGNED CHAP\.(\d+)", a["text"])
                if m:
                    chapter = int(m.group(1))
                m = re.match(r"(?:VETOED MEMO\.|POCKET VETO - VETO\.)(\d+)", a["text"])
                if m:
                    veto = int(m.group(1))

        laws = sorted({b["lawSection"] for b in live if b["lawSection"]})
        comms = sorted({f"{b2['chamber'][0]} · {norm_comm(c['name'])}" for b2 in live for c in b2["pastCommittees"]})
        comm_names = {norm_comm(c["name"]) for b in live for c in b["pastCommittees"]}
        text = " ".join(filter(None, [lead["title"], lead["summary"]]))

        topics = []
        for k, (label, cset, lset, _) in TOPICS.items():
            if comm_names & cset or set(laws) & lset or (k in TOPIC_WORDS and TOPIC_WORDS[k].search(lead["title"] or "")):
                topics.append(k)
        if any((b["programInfo"] or {}).get("name") in ("Department of Environmental Conservation",
                                                       "Environmental Facilities Corporation") for b in live):
            if "env" not in topics:
                topics.insert(0, "env")

        dates = [a["date"] for b in live for a in b["actions"]]

        def when(pred, mode="last"):
            ds = sorted({a["date"] for b in live for a in b["actions"] if pred(a["text"])})
            if not ds:
                return ""
            return {"first": ds[0], "last": ds[-1], "all": ";".join(ds)}[mode]

        # Key dates in the bill's path, across both houses' versions ("" if it never happened).
        key_dates = [
            when(lambda t: t.startswith(("ADVANCED TO THIRD READING", "ORDERED TO THIRD READING")), "first"),
            when(lambda t: t in ("PASSED SENATE", "REPASSED SENATE"), "all"),
            when(lambda t: t in ("PASSED ASSEMBLY", "REPASSED ASSEMBLY"), "all"),
            when(lambda t: t.startswith("DIED IN")),
            when(lambda t: t == "DELIVERED TO GOVERNOR"),
            when(lambda t: t.startswith("SIGNED CHAP")),
            when(lambda t: t.startswith(("VETOED MEMO", "POCKET VETO"))),
        ]
        first = min(dates + [b["publishDate"] for b in live if b["publishDate"]], default=None)
        last = max(dates, default=lead["status"]["actionDate"])
        prog = next(((b["programInfo"] or {}).get("name") for b in live if b["programInfo"]), None)

        rec = {
            "nums": [b["printNo"] + (b["activeVersion"] or "") for b in live],
            "base": [b["printNo"] for b in members],
            "prev": {(p["session"], p["printNo"]) for b in members for p in b.get("previousVersions", [])
                     if p["session"] < session},
            "title": lead["title"],
            "summary": lead["summary"] or "",
            "act": re.sub(r"\s+", " ", lead["actClause"] or ""),
            "lawCode": lead["lawCode"] or "",
            "law": lead["lawSection"],
            "laws": laws,
            "comms": comms,
            "topics": topics,
            "local": "local" in topics or bool(set(laws) & LOCAL_LAWS) or bool(LOCAL_WORDS.search(text)),
            "senDeleg": any(b["chamber"] == "SENATE" and b["district"] in deleg.get("SENATE", ()) for b in live),
            "asmDeleg": any(b["chamber"] == "ASSEMBLY" and b["district"] in deleg.get("ASSEMBLY", ()) for b in live),
            "budget": any(b["budget"] for b in live),
            # Passed each house at any point in the session, even if later sent back to committee.
            "passedS": any(a["text"] in ("PASSED SENATE", "REPASSED SENATE") for b in live for a in b["actions"]),
            "passedA": any(a["text"] in ("PASSED ASSEMBLY", "REPASSED ASSEMBLY") for b in live for a in b["actions"]),
            "program": f"Program bill: {prog}" if prog else None,
            "stage": stage,
            "passedIn": passed_in,
            "chapter": chapter,
            "veto": veto,
            "comm": lead["status"]["committeeName"] if stage == 0 else None,
            "first": first,
            "last": last,
            "cosp": max(b["cosponsorCount"] for b in live),
            "keyDates": key_dates,
            "votes": collect_votes(live, avotes),
            "firstComms": first_committees(live),
            "vers": [{
                "p": b["printNo"] + (b["activeVersion"] or ""),
                "sponsor": b["sponsor"],
                "district": b["district"],
                "cosponsors": (b.get("coSponsors") or []) + (b.get("multiSponsors") or []),
                "cosp": b["cosponsorCount"],
                "statusDesc": b["status"]["statusDesc"],
                "committee": b["status"]["committeeName"],
                "actions": [[a["date"], a["text"]] for a in b["actions"]],
            } for b in live],
        }
        for p in rec["base"]:
            index[p] = len(recs)
        recs.append(rec)

    # Sponsor names for the delegation checkboxes.
    names = {"SENATE": set(), "ASSEMBLY": set()}
    for b in bills.values():
        if b["district"] in deleg.get(b["chamber"], ()) and b["sponsorShort"]:
            names[b["chamber"]].add(b["sponsor"].split()[-1] if not b["sponsor"].split()[-1].rstrip(".").isupper()
                                    else b["sponsor"].split()[-2])
    names = {k: sorted(v & DELEGATION_NAMES) for k, v in names.items()}
    # If someone else holds the seat, drop that checkbox's matches as well.
    for r in recs:
        if not names["SENATE"]:
            r["senDeleg"] = False
        if not names["ASSEMBLY"]:
            r["asmDeleg"] = False
    return recs, index, raw["fetched"], names


def github_page(html):
    """Claude artifacts get a document skeleton added when published; GitHub Pages doesn't."""
    split = html.index('<div class="wrap">')
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="robots" content="noindex, nofollow">\n'
            '<style>body { margin: 0; } [hidden] { display: none !important; }</style>\n'
            + html[:split] + '\n</head>\n<body>\n' + html[split:] + '\n</body>\n</html>\n')


def assembly_resolver(session):
    """Turns the Assembly's short vote names ("Kelles", "Carroll P") into district numbers."""
    path = os.path.join(HERE, "data", f"contacts_{session}.json")
    seats = json.load(open(path)).get("people", {}) if os.path.exists(path) else {}
    by_last = defaultdict(list)
    for seat, p in seats.items():
        if seat[0] == "A":
            words = p["key"].split()
            by_last[words[-1]].append((words[0], int(seat[2:])))
    cache = {}

    def resolve(short):
        if short in cache:
            return cache[short]
        parts = short.replace(".", "").split()
        last = re.sub(r"[^a-z-]", "", parts[0].lower()) if parts else ""
        # Multi-word last names ("Pheffer Amato", "De Los Santos"): try the whole name, then its end.
        full = re.sub(r"[^a-z\s-]", "", short.lower())
        initials = parts[-1] if len(parts) > 1 and parts[-1].isupper() and len(parts[-1]) <= 3 else ""
        cands = by_last.get(full.replace(" " + initials.lower(), "").split()[-1] if initials else full.split()[-1], []) if full else []
        if not cands and full:
            # The Assembly cuts long names short ("Chandler-Waterm"): match the start of a last name.
            stem = full.split()[-1]
            cands = [c for last, cs in by_last.items() if len(stem) >= 5 and last.startswith(stem) for c in cs]
        if len(cands) > 1 and initials:
            cands = [c for c in cands if c[0][0].upper() in initials] or cands
        if short.strip().lower() in ("mr. speaker", "mr speaker", "madam speaker") and "A" in LEADERS:
            speaker = name_key(LEADERS["A"][0]).split()
            cands = [c for c in by_last.get(speaker[-1], []) if c[0] == speaker[0]]
        cache[short] = cands[0][1] if len(cands) == 1 else None
        return cache[short]
    return resolve


def parties(session, recs):
    """Party ("D" or "R") for each legislator name as the bill data spells it, keyed by
    (house, name). Names are tied to parties through the seat each sponsor holds: sitting
    members from the contacts file, earlier holders from the Open States archive."""
    path = os.path.join(HERE, "data", f"contacts_{session}.json")
    seats = json.load(open(path)).get("people", {}) if os.path.exists(path) else {}
    hpath = os.path.join(HERE, "data", "seat_parties.json")
    history = json.load(open(hpath)) if os.path.exists(hpath) else {}
    by_last = defaultdict(set)
    for seat, holders in history.items():
        for h in holders:
            if name_key(h["last"]).split():
                by_last[(seat[0], name_key(h["last"]).split()[-1])].add(h["party"])

    def held(h):
        return (not h["start"] or h["start"] <= str(session + 1)) and (not h["end"] or h["end"] >= str(session))

    out = {}
    for r in recs:
        for v in r["vers"]:
            if not v["sponsor"]:
                continue
            house, last = v["p"][0], name_key(v["sponsor"]).split()[-1]
            seat_id = f"{house}:{v.get('district')}"
            seat, code = seats.get(seat_id), None
            if seat and seat["key"].split()[-1] == last:
                p = seat.get("party") or ""
                code = "D" if "Democrat" in p else "R" if "Republican" in p else None
            if not code:
                code = next((h["party"] for h in history.get(seat_id, [])
                             if held(h) and name_key(h["last"]).split()[-1:] == [last]), None)
            if not code and len(by_last.get((house, last), ())) == 1:
                code = next(iter(by_last[(house, last)]))
            if code:
                out[(house, v["sponsor"])] = code
    return out


def bill_parties(r, party_of):
    """How many sponsors and co-sponsors of each party are on either version: [D, R]."""
    found = {}
    for v in r["vers"]:
        for n in [v["sponsor"]] + v.get("cosponsors", []):
            p = party_of.get((v["p"][0], n))
            if p:
                found[(v["p"][0], n)] = p
    vals = list(found.values())
    return [vals.count("D"), vals.count("R")]


def legislators(session):
    """Current legislators with a short page address each: last name, or first-last when shared."""
    path = os.path.join(HERE, "data", f"contacts_{session}.json")
    if not os.path.exists(path):
        return []
    raw = json.load(open(path))
    seats = raw.get("people", {})
    since = raw.get("since", {})
    last = lambda p: p["key"].split()[-1]

    def committees_of(seat, p):
        house = seat[0]
        src = raw.get("senateCommittees" if house == "S" else "assemblyCommittees", {})
        def same(n):
            # Committee lists spell names their own way ("Patrick J. Carroll"); match on the
            # last name when it's unique in the house, else last name and first initial.
            k = name_key(n)
            if not k or k.split()[-1] != last(p):
                return False
            return k == p["key"] or house_counts[(house, last(p))] == 1 or k[0] == p["key"][0]
        found = [(c["name"], same(c.get("chair") or "")) for c in src.values() if any(same(m) for m in c.get("members", []))]
        return [{"name": n.replace(" And ", " and "), "chair": ch} for n, ch in sorted(found, key=lambda x: (not x[1], x[0]))]
    counts = Counter(last(p) for p in seats.values())
    house_counts = Counter((seat[0], last(p)) for seat, p in seats.items())
    out = []
    for seat, p in sorted(seats.items(), key=lambda kv: kv[1]["key"].split()[-1]):
        house, district = seat.split(":")
        slug = last(p) if counts[last(p)] == 1 else p["key"].replace(" ", "-")
        out.append({"id": seat, "slug": slug, "name": p["name"], "title": "Sen." if house == "S" else "Asm.",
                    "house": house, "district": int(district), "email": p.get("email"), "phone": p.get("phone"), "phones": p.get("phones"),
                    "url": p.get("url"), "party": p.get("party"), "image": p.get("image"),
                    "since": since.get(seat), "committees": committees_of(seat, p)})
    return out


def contacts_for(session, recs, delegation_names):
    """Who to contact for the current session: committee chairs (and whether our legislators
    sit on each committee), our legislators, and email, phone and page for each person."""
    path = os.path.join(HERE, "data", f"contacts_{session}.json")
    if not os.path.exists(path):
        return None
    raw = json.load(open(path))
    seats = raw.get("people", {})  # "S:52" -> {name, key, email, phone, url}
    asm_members = raw.get("assemblyMembers", {})
    people = {}

    def lookup(name, house, district=None):
        """Contact details for a legislator, by seat when known (checking it's the same person)."""
        key = name_key(name)
        p = seats.get(f"{house}:{district}") if district else None
        if p and p["key"].split()[-1] != key.split()[-1]:
            p = None  # someone else holds that seat now
        if not p:
            hits = [v for k, v in seats.items() if k[0] == house and v["key"] == key]
            if not hits:
                hits = [v for k, v in seats.items() if k[0] == house and v["key"].split()[-1] == key.split()[-1]]
            p = hits[0] if len(hits) == 1 else None
        if p:
            return {"url": p["url"], "email": p["email"], "phone": p["phone"], "phones": p.get("phones")}
        if house == "S":
            return {"url": senate_url(name)}
        m = asm_members.get(key) or {}
        return {"url": m.get("url"), "email": m.get("email")}

    def person(name, house, district=None):
        if name and name not in people:
            people[name] = lookup(name, house, district)
        return name

    ours = {"S": set(delegation_names.get("SENATE", [])), "A": set(delegation_names.get("ASSEMBLY", []))}

    def ours_on(members, house):
        return sorted({n for n in ours[house] for m in members if name_key(m).endswith(" " + n.lower())})

    committees = {}
    for house, key in (("S", "senateCommittees"), ("A", "assemblyCommittees")):
        for k, c in raw.get(key, {}).items():
            committees[f"{house}:{k}"] = {
                "name": c["name"],
                "chair": person(c.get("chair"), house),
                "meets": c.get("meets"),
                "url": c.get("url"),
                "ours": ours_on(c.get("members", []), house),
            }
    for r in recs:
        for v in r["vers"]:
            person(v["sponsor"], v["p"][0], v.get("district"))
    reps = []
    for house, title in (("S", "Sen."), ("A", "Asm.")):
        for district in sorted(delegation(session).get("SENATE" if house == "S" else "ASSEMBLY", ())):
            seat = seats.get(f"{house}:{district}")
            if seat and seat["key"].split()[-1] in {n.lower() for n in ours[house]}:
                name = next((n for n in people if name_key(n) == seat["key"]), seat["name"])
                people.setdefault(name, lookup(name, house, district))
                reps.append({"title": title, "name": name, "house": house, "last": seat["key"].split()[-1]})
    leaders = {}
    for house, (name, role) in LEADERS.items():
        if any(k[0] == house and v["key"] == name_key(name) for k, v in seats.items()):
            person(name, house)
            leaders[house] = {"name": name, "role": role}
    return {"fetched": raw.get("fetched"), "committees": committees, "people": people, "reps": reps, "leaders": leaders}


def choose_page(legs):
    """A small page for a shared last name: pick which legislator you meant."""
    last = legs[0]["name"].split()[-1]
    items = "\n".join(
        f'<li><a href="../{l["slug"]}/">{l["title"]} {html_escape(l["name"])}</a> '
        f'<span>{"Senate" if l["house"] == "S" else "Assembly"} District {l["district"]}</span></li>' for l in legs)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Which {html_escape(last)}? · Albany Bill Tracker</title>
<style>
:root {{ --bg: #f6f8fb; --fg: #14213d; --muted: #4a5878; --link: #1d3b78; color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #0f1626; --fg: #e6ebf5; --muted: #a3b0c9; --link: #8fb0f0; color-scheme: dark; }} }}
body {{ margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; padding: 40px max(16px, env(safe-area-inset-left, 0px)); }}
main {{ max-width: 560px; margin: 0 auto; }} h1 {{ font-size: 26px; margin: 0 0 16px; }}
ul {{ list-style: none; padding: 0; margin: 0 0 24px; display: grid; gap: 12px; }} a {{ color: var(--link); font-weight: 600; }}
li span {{ color: var(--muted); font-size: 14px; margin-left: 8px; }}
</style></head><body><main>
<h1>Which {html_escape(last)}?</h1>
<ul>
{items}
</ul>
<p><a href="../">All bills</a></p>
</main></body></html>
"""


def html_escape(x):
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

# ---- Statistics people can act on ----
# Titles of laws that are local or ceremonial (naming a road, one property's tax exemption,
# one town's arrangement), counted separately from substantive laws.
CEREMONIAL = re.compile(
    r"designat|dedicat|\bnam(e|es|ing)\b.*\b(highway|bridge|road|route|interchange|building)|"
    r"(to file|to receive|retroactive).*(exemption|exempt status)|real property tax exemption|"
    r"legaliz\w*,? validat|in the (town|village|city|county) of|of the (town|village|city|county) of|"
    r"authoriz\w* (the )?(town|village|city|county|school district|fire district)", re.I)


def reached(r):
    """How far a bill ever got this session (not where it is now)."""
    k = r["keyDates"]
    passed_s, passed_a = bool(k[1]), bool(k[2])
    return {
        "floor": bool(k[0]) or passed_s or passed_a,
        "passS": passed_s,
        "passA": passed_a,
        # Each house passing its own version, or passing in different years, isn't passing both.
        "both": r["stage"] >= 3,
        "law": r["stage"] == 5,
    }


def insights(loaded, hist, current):
    past = [s for s in sorted(loaded) if s != current]
    topics = ["all"] + list(TOPICS)
    has = lambda r, t: t == "all" or t in r["topics"]

    current_comms = {f"{h} · {n}" for r in loaded[current][0] for h, n, _ in r["firstComms"]}

    # Where bills die: share of bills each committee let out, current session and past sessions.
    def committee_table(sessions, minimum=True):
        out = {t: defaultdict(lambda: [0, 0, 0]) for t in topics}
        for s in sessions:
            for r in loaded[s][0]:
                for house, name, left in r["firstComms"]:
                    for t in topics:
                        if has(r, t):
                            c = out[t][f"{house} · {name}"]
                            c[0] += 1
                            c[1] += left
                            c[2] += r["stage"] == 5
        # Only committees that exist this session; defunct ones would only confuse.
        return {t: {k: v for k, v in d.items() if k in current_comms and (not minimum or v[0] >= (40 if t == "all" else 15))} for t, d in out.items()}

    # What usually happens next: of bills that reached each point, how many became law.
    odds = {t: defaultdict(lambda: [0, 0]) for t in topics}
    for s in past:
        for r in loaded[s][0]:
            got = reached(r)
            points = {"intro": True, "floor": got["floor"], "passS": got["passS"], "passA": got["passA"], "both": got["both"]}
            for t in topics:
                if has(r, t):
                    for p, ok in points.items():
                        if ok:
                            odds[t][p][0] += 1
                            odds[t][p][1] += got["law"]

    # Timing: how much floor action comes at the very end of each year's session.
    timing = []
    for s in past:
        for year in (s, s + 1):
            dates = [d for r in loaded[s][0] for i in (1, 2) for d in r["keyDates"][i].split(";") if d.startswith(str(year))]
            if not dates:
                continue
            # The regular session ends in June; later votes are special sessions.
            regular = [d for d in dates if d <= f"{year}-07-15"]
            if not regular:
                continue
            # A one-day special session (e.g. July 2022) isn't the end of the regular session:
            # use the last day with a full slate of votes.
            per_day = Counter(regular)
            last = max(d for d, n in per_day.items() if n >= 20)
            from datetime import date, timedelta
            cut = (date.fromisoformat(last) - timedelta(days=21)).isoformat()
            timing.append({"year": year, "votes": len(regular), "lastVote": last,
                           "final3wk": sum(cut < d <= last for d in regular)})
    signed = [r["keyDates"][5] for s in past for r in loaded[s][0] if r["keyDates"][5]]
    # The governor's decisions: by month (past sessions) and by calendar year (all sessions).
    gov_months = defaultdict(lambda: [0, 0])
    gov_years = defaultdict(lambda: [0, 0])
    for s in sorted(loaded):
        for r in loaded[s][0]:
            for i, kind in ((5, 0), (6, 1)):
                d = r["keyDates"][i]
                if not d:
                    continue
                who = "Cuomo" if d < "2021-08-24" else "Hochul"
                if s != current:
                    gov_months[f"{who}|{d[5:7]}"][kind] += 1
                gov_years[f"{d[:4]}|{who}"][kind] += 1
    late_sign = sum(d[5:7] in ("10", "11", "12") for d in signed)

    # Persistence: how many earlier sessions laws took, and what happens to bills that die.
    persist = {t: [0, 0, 0, 0, 0] for t in topics}  # laws with 0, 1, 2, 3+ earlier sessions; total
    for s in past[1:]:
        for i, r in enumerate(loaded[s][0]):
            if r["stage"] != 5:
                continue
            n = len({e[0] for e in hist[s][i].values() if e[0] < s})
            for t in topics:
                if has(r, t):
                    persist[t][min(n, 3)] += 1
                    persist[t][4] += 1
    comeback = {t: [0, 0, 0] for t in topics}  # died in committee; reintroduced next session; later became law
    for s in past[:-1]:
        nxt = s + 2
        for i, r in enumerate(loaded[s][0]):
            if r["stage"] != 0:
                continue
            later = [e for e in hist[s][i].values() if e[0] > s]
            for t in topics:
                if has(r, t):
                    c = comeback[t]
                    c[0] += 1
                    c[1] += any(e[0] == nxt for e in later)
                    c[2] += any(e[2] == 5 for e in later)

    # What happened to bills that died, by how far they got: [died, back next session, later law].
    fate = {t: {k: [0, 0, 0] for k in ("committee", "floor", "oneHouse", "vetoed")} for t in topics}
    for s in past[:-1]:
        nxt = s + 2
        for i, r in enumerate(loaded[s][0]):
            k = {0: "committee", 1: "floor", 2: "oneHouse", 6: "vetoed"}.get(r["stage"])
            if not k:
                continue
            later = [e for e in hist[s][i].values() if e[0] > s]
            for t in topics:
                if has(r, t):
                    c = fate[t][k]
                    c[0] += 1
                    c[1] += any(e[0] == nxt for e in later)
                    c[2] += any(e[2] == 5 for e in later)

    # The current session's most persistent bills: introduced in the most earlier sessions.
    cur_recs = loaded[current][0]
    tries = []
    for i, r in enumerate(cur_recs):
        earlier = sorted({e[0] for e in hist[current][i].values() if e[0] < current})
        if len(earlier) >= 3:
            best = max((e[2] for e in hist[current][i].values() if e[0] < current), default=-1)
            tries.append((len(earlier), i, earlier[0], best))
    tries.sort(key=lambda x: (-x[0], -rank(x[3]) if x[3] >= 0 else 1, x[1]))
    persistent = {}
    for t in topics:
        rows = [x for x in tries if has(cur_recs[x[1]], t)][:12]
        persistent[t] = [[cur_recs[i]["nums"][0], cur_recs[i]["title"], n, first, best, cur_recs[i]["stage"]] for n, i, first, best in rows]

    # Co-sponsor counts and outcomes, past sessions: [bills, passed both houses, became law] per range.
    cosp_bins = [(0, 0), (1, 4), (5, 9), (10, 19), (20, 39), (40, 10 ** 6)]
    cosp = {t: [[0, 0, 0] for _ in cosp_bins] for t in topics}
    for s in past:
        for r in loaded[s][0]:
            j = next(i for i, (lo, hi) in enumerate(cosp_bins) if lo <= r["cosp"] <= hi)
            for t in topics:
                if has(r, t):
                    c = cosp[t][j]
                    c[0] += 1
                    c[1] += r["stage"] >= 3
                    c[2] += r["stage"] == 5

    # The same by party of sponsors and co-sponsors: both parties, Democrats only, Republicans only.
    party = {}
    for s in sorted(loaded):
        party_of = parties(s, loaded[s][0])
        key = "past" if s != current else "current"
        for r in loaded[s][0]:
            d, rep = bill_parties(r, party_of)
            k = "DR" if d and rep else "D" if d else "R" if rep else None
            if not k:
                continue
            for t in topics:
                if has(r, t):
                    c = party.setdefault(key, {}).setdefault(t, {}).setdefault(k, [0, 0, 0])
                    c[0] += 1
                    c[1] += r["stage"] >= 3
                    c[2] += r["stage"] == 5

    # When things happen, by month of the two-year session (0-11 first year, 12-23 second):
    # bills introduced, first approved by a committee, first passed by each house.
    def month_counts(sessions):
        out = {t: {k: [0] * 24 for k in ("intro", "comm", "passS", "passA", "signed", "vetoed")} for t in topics}
        for s in sessions:
            for r in loaded[s][0]:
                k = r["keyDates"]
                when = {"intro": r["first"] or "", "comm": k[0], "passS": k[1].split(";")[0], "passA": k[2].split(";")[0],
                        "signed": k[5] if r["stage"] == 5 else "", "vetoed": k[6] if r["stage"] == 6 else ""}
                for key, d in when.items():
                    if len(d) < 7 or d[:4] > str(s + 1):
                        continue
                    # Bills prefiled in late fall count as introduced when the session opens.
                    if d[:4] < str(s):
                        d = f"{s}-01"
                    m = (int(d[:4]) - s) * 12 + int(d[5:7]) - 1
                    for t in topics:
                        if has(r, t):
                            out[t][key][m] += 1
        return out

    # Bills that passed both houses but that the governor's office still hadn't requested on
    # today's date in the same year of past sessions: how many became law. Bills still waiting
    # late in the year are more often vetoed than bills overall.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/New_York")).date()
    year = today.year - current
    waiting = None
    if year in (0, 1):
        md = today.strftime("%m-%d")
        n = law = 0
        for s in past:
            cut = f"{s + year}-{md}"
            for r in loaded[s][0]:
                k = r["keyDates"]
                ps, pa = k[1].split(";")[0], k[2].split(";")[0]
                decided = min(filter(None, [k[5], k[6]]), default="")
                if not (ps and pa) or max(ps, pa) > cut or (decided and decided <= cut) or (k[4] and k[4] <= cut):
                    continue
                n += 1
                law += r["stage"] == 5
        waiting = {"date": md, "year": year, "n": n, "law": law}

    return {
        "waiting": waiting,
        "months": month_counts(past),
        "monthsNow": month_counts([current]),
        "cosponsors": cosp,
        "party": party,
        "fate": fate,
        "persistent": persistent,
        "pastSessions": past,
        "committees": {"current": committee_table([current], minimum=False), "past": committee_table(past)},
        "odds": {t: dict(v) for t, v in odds.items()},
        "timing": timing,
        "lateSigning": [late_sign, len(signed)],
        "govMonths": dict(sorted(gov_months.items())),
        "govYears": [[k.split("|")[0], k.split("|")[1], v[0], v[1]] for k, v in sorted(gov_years.items())],
        "persistence": persist,
        "comeback": comeback,
    }


def profiles(session, recs, legs, party_of):
    """Each sitting legislator's numbers this session, and the median for their party in their house."""
    resolve = assembly_resolver(session)
    by_seat = {L["id"]: L for L in legs}
    last_of = {L["id"]: name_key(L["name"]).split()[-1] for L in legs}
    stats = {L["id"]: {"sponsored": 0, "floor": 0, "passedHouse": 0, "both": 0, "laws": 0, "lawsLocal": 0,
                       "otherParty": 0, "floorVotes": 0, "missed": 0, "comms": {}} for L in legs}
    first_bill, votes_seen = {}, []
    for r in recs:
        got = reached(r)
        local = bool(CEREMONIAL.search(r["title"] or ""))
        for v in r["vers"]:
            house = v["p"][0]
            seat = f"{house}:{v.get('district')}"
            if seat not in stats or name_key(v["sponsor"] or "").split()[-1:] != [last_of[seat]]:
                continue
            st = stats[seat]
            st["sponsored"] += 1
            st["floor"] += got["floor"]
            st["passedHouse"] += got["passS"] if house == "S" else got["passA"]
            st["both"] += got["both"]
            # The committee their own house sent the bill to first: [bills, approved, became law].
            for h, name, left in r["firstComms"]:
                if h == house:
                    c = st["comms"].setdefault(name, [0, 0, 0])
                    c[0] += 1
                    c[1] += left
                    c[2] += got["law"]
                    break
            if got["law"]:
                st["lawsLocal" if local else "laws"] += 1
            mine = "D" if "Democrat" in (by_seat[seat].get("party") or "") else "R" if "Republican" in (by_seat[seat].get("party") or "") else None
            others = {party_of.get((vv["p"][0], n)) for vv in r["vers"] for n in [vv["sponsor"]] + vv.get("cosponsors", [])}
            st["otherParty"] += bool(mine and (others - {mine, None}))
        for v in r["vers"]:
            seat = f"{v['p'][0]}:{v.get('district')}"
            if seat in stats and v["actions"] and name_key(v["sponsor"] or "").split()[-1:] == [last_of[seat]]:
                first_bill[seat] = min(first_bill.get(seat, "9999"), v["actions"][0][0])
        for h, kind, comm, date, y, n, ny in r["votes"]:
            if kind != "F":
                continue
            absent = set()
            for (mh, who), code in ny:
                if code in ("E", "A"):
                    d = who if mh == "S" else resolve(who)
                    if d:
                        absent.add(f"{mh}:{d}")
            votes_seen.append((h, date, absent))
    # Members who joined during the session: count only votes from their first bill on.
    late = f"{session}-03-01"
    for seat, d in first_bill.items():
        if d >= late:
            stats[seat]["start"] = d
    for h, date, absent in votes_seen:
        for seat in stats:
            if seat[0] == h and (first_bill.get(seat, "") < late or date >= first_bill[seat]):
                stats[seat]["floorVotes"] += 1
                stats[seat]["missed"] += seat in absent
    groups = defaultdict(list)
    for seat, st in stats.items():
        p = by_seat[seat].get("party") or ""
        code = "D" if "Democrat" in p else "R" if "Republican" in p else None
        if code and st["sponsored"]:
            groups[f"{seat[0]}:{code}"].append(st)

    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2

    peers = {}
    for g, sts in groups.items():
        peers[g] = {"members": len(sts)}
        for k in ("sponsored", "floor", "passedHouse", "both", "laws", "lawsLocal", "otherParty", "missed", "floorVotes"):
            peers[g][k] = median([x[k] for x in sts])
    for st in stats.values():
        st["comms"] = sorted(([k] + v for k, v in st["comms"].items()), key=lambda c: -c[1])
    return stats, peers


def person_history(loaded, current, legs):
    """Each sitting legislator's bills in every loaded session, by the name they sponsor under,
    with the typical (median) member of the same party and house that session:
    [[session, house, sponsored, passed both houses, laws, typical sponsored, typical both, typical laws]]."""
    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2

    match = member_matcher(legs)
    out = defaultdict(list)
    for s in sorted(loaded):
        recs = loaded[s][0]
        party_of = parties(s, recs)
        counts = defaultdict(lambda: [0, 0, 0])  # (house, sponsor) -> [bills, both, laws]
        district = {}
        for r in recs:
            got = reached(r)
            for v in r["vers"]:
                if v["sponsor"] and v.get("district"):
                    district[(v["p"][0], v["sponsor"])] = v["district"]
            for who in {(v["p"][0], v["sponsor"]) for v in r["vers"] if v["sponsor"]}:
                c = counts[who]
                c[0] += 1
                c[1] += got["both"]
                c[2] += got["law"]
        groups = defaultdict(list)
        for who, c in counts.items():
            if party_of.get(who):
                groups[(who[0], party_of[who])].append(c)
        typical = {g: [median([c[i] for c in cs]) for i in range(3)] for g, cs in groups.items()}
        for (house, name), c in counts.items():
            seat = match(house, name, district.get((house, name)))
            if seat:
                ty = typical.get((house, party_of.get((house, name))), [0, 0, 0])
                out[seat].append([s, house] + c + ty)
    return dict(out)


def member_matcher(legs):
    """Matches a name as bills or committee lists spell it ("Joseph P. Addabbo Jr.") to a
    current legislator listed under another form ("Joe Addabbo"): by seat when the district is
    known, else by last name within the house, else last name plus first initial."""
    by_seat = {L["id"]: L for L in legs}
    by_last = defaultdict(list)
    for L in legs:
        k = name_key(L["name"])
        if k:
            by_last[(L["id"][0], k.split()[-1])].append(L)

    def match(house, name, district=None):
        k = name_key(name or "")
        if not k:
            return None
        last = k.split()[-1]
        L = by_seat.get(f"{house}:{district}") if district else None
        if L and name_key(L["name"]).split()[-1:] == [last]:
            return L["id"]
        cands = by_last.get((house, last), [])
        for pick in (cands, [c for c in cands if name_key(c["name"]) == k], [c for c in cands if name_key(c["name"])[0] == k[0]]):
            if len(pick) == 1:
                return pick[0]["id"]
        return None
    return match


def net_counts(recs, key):
    """Co-sponsorship counts for the network chart. key(house, sponsor name) gives a node id or
    None. Returns bills sponsored per node, co-sponsor -> sponsor counts (same house), and
    Senate sponsor -> Assembly sponsor counts for bills both carried."""
    spons, w, cross = Counter(), Counter(), Counter()
    for r in recs:
        carriers = {"S": set(), "A": set()}
        for v in r["vers"]:
            h = v["p"][0]
            s = key(h, v["sponsor"], v.get("district")) if v["sponsor"] else None
            if not s:
                continue
            spons[s] += 1
            carriers[h].add(s)
            for c in v.get("cosponsors", []):
                ck = key(h, c)
                if ck and ck != s:
                    w[(ck, s)] += 1
        for a in carriers["S"]:
            for z in carriers["A"]:
                cross[(a, z)] += 1
    return spons, w, cross


def net_views(spons, w, cross, info):
    """The network for the Senate, the Assembly and both houses, as the page draws it:
    {view: {"nodes": [[id, label, party, bills]], "links": [[a, b, share, kind]]}}. Each member
    keeps their strongest few ties; the same rules as the live chart on the current page."""
    out = {}
    for sel in ("S", "A", "B"):
        houses = ("S", "A") if sel == "B" else (sel,)
        ids = [k for k in spons if info.get(k) and k[0] in houses]
        idset = set(ids)

        def pairs(m, kind, directed):
            res = {}
            for (a, s), c in m.items():
                if a not in idset or s not in idset or c < 3:
                    continue
                share = c / spons[s] if directed else c / min(spons[a], spons[s])
                k = tuple(sorted((a, s)))
                p = res.setdefault(k, [k[0], k[1], 0.0, kind])
                p[2] = max(p[2], share)
            return list(res.values())
        keep = {}
        groups = [(pairs(w, "co", True), 3 if sel == "B" else 4)]
        if sel == "B":
            groups.append((pairs(cross, "x", False), 3))
        for lst, n in groups:
            for x in ids:
                mine = sorted((p for p in lst if x in p[:2]), key=lambda p: -p[2])[:n]
                for p in mine:
                    keep[(p[0], p[1], p[3])] = p
        # Members with no strong ties are drawn too, as dots on their own.
        out[sel] = {"nodes": [[k, info[k][0], info[k][1], spons[k]] for k in ids],
                    "links": [[a, b, round(s, 3), kind] for a, b, s, kind in keep.values()]}
    return out


def session_network(s, recs):
    """One session's network, with members named as that session's bills name them."""
    party_of = parties(s, recs)
    key = lambda h, n, d=None: f"{h}:{n}" if party_of.get((h, n)) else None
    info = {f"{h}:{n}": [f"{'Sen.' if h == 'S' else 'Asm.'} {n}", p] for (h, n), p in party_of.items()}
    return net_views(*net_counts(recs, key), info)


def network_since(loaded, legs):
    """Today's members, with ties added up over every loaded session they served together."""
    key = member_matcher(legs)
    spons, w, cross = Counter(), Counter(), Counter()
    for s in sorted(loaded):
        a, b2, c = net_counts(loaded[s][0], key)
        spons += a
        w += b2
        cross += c
    info = {}
    for L in legs:
        p = L.get("party") or ""
        code = "D" if "Democrat" in p else "R" if "Republican" in p else None
        if code:
            info[L["id"]] = [f"{L['title']} {L['name']}", code]
    return net_views(spons, w, cross, info)


def outcomes(recs):
    """Counts per topic: [bills, passed both houses or further, signed, vetoed, passed one house only]."""
    out = defaultdict(lambda: [0, 0, 0, 0, 0])
    for r in recs:
        for t in ["all"] + r["topics"]:
            c = out[t]
            c[0] += 1
            c[1] += r["stage"] >= 3
            c[2] += r["stage"] == 5
            c[3] += r["stage"] == 6
            c[4] += r["stage"] == 2
    return dict(out)


def main():
    loaded = {s: load_session(s) for s in SESSIONS}
    urls = json.load(open(URLS_FILE)) if os.path.exists(URLS_FILE) else {}
    current_session = max(SESSIONS)
    if GITHUB:
        urls = {str(s): ("./" if s == current_session else f"{s}.html") for s in SESSIONS}

    # Cross-session links. Each bill lists its own earlier versions; later sessions' lists
    # give the reverse direction. Entries: [session, "S1/A2", stage, chapter, veto].
    def entry(s, i):
        r = loaded[s][0][i]
        return [s, " / ".join(r["nums"]), r["stage"], r["chapter"] or 0, r["veto"] or 0]

    old_path = os.path.join(HERE, "data", "old_outcomes.json.gz")
    old = json.load(gzip.open(old_path, "rt")) if os.path.exists(old_path) else {}
    hist = {s: defaultdict(dict) for s in SESSIONS}  # session -> rec index -> {(s, idx|printNo): entry}
    for s in SESSIONS:
        recs, index = loaded[s][0], loaded[s][1]
        for i, r in enumerate(recs):
            for ps, pp in r["prev"]:
                if ps in loaded and pp in loaded[ps][1]:
                    j = loaded[ps][1][pp]
                    hist[s][i][(ps, j)] = entry(ps, j)
                    hist[ps][j][(s, i)] = entry(s, i)
                elif ps in loaded:
                    # Version exists but was withdrawn (stricken), so it isn't in that session's list.
                    e = hist[s][i].setdefault((ps, "withdrawn"), [ps, "", -2, 0, 0])
                    e[1] = " / ".join(filter(None, e[1].split(" / ") + [pp]))
                else:
                    # Session not downloaded: list its bill numbers together, with the outcome
                    # from the short list of older sessions when there is one.
                    e = hist[s][i].setdefault((ps, None), [ps, "", -1, 0, 0])
                    e[1] = " / ".join(sorted(filter(None, e[1].split(" / ") + [pp]), key=lambda n: n[0] != "S"))
                    codes = [old.get(str(ps), {}).get(n[:1] + re.sub(r"[A-Z]+$", "", n[1:]))
                             for n in e[1].split(" / ")]
                    codes = [c for c in codes if c is not None]
                    if codes:
                        st = max((c // 4 for c in codes), key=rank)
                        flags = 0
                        for c in codes:
                            flags |= c & 3
                        e[2] = 3 if rank(st) < rank(3) and flags == 3 else st

    summary = {s: outcomes(loaded[s][0]) for s in SESSIONS}
    current = max(SESSIONS)
    insight = insights(loaded, hist, current)

    for session in ONLY:
        recs, _, fetched, names = loaded[session]
        law_count, comm_count = Counter(), Counter()
        for r in recs:
            law_count.update(r["laws"])
            comm_count.update(r["comms"])

        # Embedded in the HTML, since the page can't fetch side files. Repeated strings go
        # in one table and records become arrays to keep the page under the 16 MB limit.
        strings, sidx = [], {}

        def S(x):
            if x is None:
                return -1
            if x not in sidx:
                sidx[x] = len(strings)
                strings.append(x)
            return sidx[x]

        party_of = parties(session, recs)
        resolve = assembly_resolver(session)
        # Senate committee agendas (current session only): when a committee takes up the bill.
        apath = os.path.join(HERE, "data", f"agendas_{session}.json")
        agendas = json.load(open(apath)) if session == current and os.path.exists(apath) else {}

        def agenda_of(r):
            seen = []
            for v in r["vers"]:
                for c, w in agendas.get(re.sub(r"[A-Z]$", "", v["p"]), []):
                    entry = [c.replace(" And ", " and "), w]
                    if entry not in seen:
                        seen.append(entry)
            return sorted(seen, key=lambda x: x[1])

        def member_id(m):
            house, who = m
            if house == "S":
                return f"S:{who}"
            d = resolve(who)
            return f"A:{d}" if d else f"A?{who}"

        def enc_votes(votes):
            return [[h, kind, S(comm), date.replace("-", ""), y, n, [[S(member_id(m)), code] for m, code in ny]]
                    for h, kind, comm, date, y, n, ny in votes]
        rows = []
        for i, r in enumerate(recs):
            flags = (r["local"] and 1) | (r["senDeleg"] and 2) | (r["budget"] and 4) | (r["asmDeleg"] and 8) | (r["passedS"] and 16) | (r["passedA"] and 32)
            vers = [[v["p"], S(v["sponsor"]), v["cosp"], S(v["statusDesc"]), S(v["committee"]),
                     [[a[0].replace("-", ""), S(a[1])] for a in v["actions"]],
                     [S(n) for n in v["cosponsors"]] if session == current else [], v.get("district") or 0] for v in r["vers"]]
            h = sorted(hist[session][i].values(), key=lambda e: (e[0], e[1]))
            rows.append([r["title"], r["summary"][:2500], [S(x) for x in r["laws"]], [S(x) for x in r["comms"]],
                         r["topics"], flags, r["stage"], r["passedIn"] or "", r["chapter"] or 0, r["veto"] or 0,
                         S(r["comm"]), r["last"].replace("-", ""), r["cosp"], r["act"], r["lawCode"],
                         S(r["program"]), S(r["law"]), vers, max(session, int((r["first"] or str(session))[:4])), h,
                         [d.replace("-", "") for d in [r["first"] or ""] + r["keyDates"]],
                         bill_parties(r, party_of), enc_votes(r["votes"]),
                         [[S(c), w] for c, w in agenda_of(r)]])

        data = {
            "session": session,
            "current": session == current,
            "fetched": fetched,
            "topics": {k: v[0] for k, v in TOPICS.items()},
            "lawList": sorted(law_count.items()),
            "commList": sorted(comm_count.items()),
            "delegation": names,
            "sessions": [{"session": s, "url": urls.get(str(s))} for s in SESSIONS],
            "outcomes": {str(s): summary[s] for s in SESSIONS},
            "insights": insight,
            # Past pages don't carry co-sponsor names, so their network is worked out here.
            "network": session_network(session, recs) if session != current else None,
            # Date of the last floor vote in either house this session.
            "lastVote": max((d for r in recs for i in (1, 2) for d in r["keyDates"][i].split(";")), default=""),
            "strings": strings,
            "rows": rows,
        }
        if session == current:
            data["contacts"] = contacts_for(session, recs, names)
            data["legislators"] = legislators(session)
            data["profiles"], data["peers"] = profiles(session, recs, data["legislators"], party_of)
            data["networkSince"] = network_since(loaded, data["legislators"])
            # Without legislators the site would lose every legislator page and contact; stop
            # so yesterday's site stays up rather than publishing a broken one.
            if GITHUB and not data["legislators"]:
                raise SystemExit("No legislators in the contacts file; not building")
            for seat, rows in person_history(loaded, current, data["legislators"]).items():
                if seat in data["profiles"]:
                    data["profiles"][seat]["history"] = rows
        payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
        if GITHUB:
            # On GitHub Pages the data is a separate file the page fetches, so the
            # per-legislator pages can share it.
            os.makedirs(os.path.join(GITHUB, "data"), exist_ok=True)
            with open(os.path.join(GITHUB, "data", f"{session}.json"), "w") as f:
                f.write(payload)
        template = open(TEMPLATE).read()
        if session != current:
            template = template.replace("<title>Albany Bill Tracker</title>",
                                        f"<title>Albany Bill Tracker {session}–{str(session + 1)[2:]}</title>", 1)
        marker = '<script type="application/json" id="bill-data"></script>'
        assert marker in template, "template is missing the data marker"
        html = template.replace(marker, f'<script type="application/json" id="bill-data">{payload}</script>')
        if GITHUB:
            out = os.path.join(GITHUB, "index.html" if session == current else f"{session}.html")
            html = github_page(template.replace(marker, f'<script type="application/json" id="bill-data" data-src="data/{session}.json" data-root="{SITE_URL}"></script>'))
            if session == current:
                for leg in data.get("legislators", []):
                    page = template.replace(marker, f'<script type="application/json" id="bill-data" data-src="../data/{session}.json" data-base="../" data-root="{SITE_URL}"></script>')
                    preset = json.dumps({"who": leg["id"]}).replace('"', "&quot;")
                    page = page.replace("<title>Albany Bill Tracker</title>",
                                        f'<title>{leg["title"]} {leg["name"]} · Albany Bill Tracker</title>\n<meta name="abt-preset" content="{preset}">', 1)
                    os.makedirs(os.path.join(GITHUB, leg["slug"]), exist_ok=True)
                    with open(os.path.join(GITHUB, leg["slug"], "index.html"), "w") as f:
                        f.write(github_page(page))
                # /watchlist/: the same page, opened to the visitor's own watchlist.
                page = template.replace(marker, f'<script type="application/json" id="bill-data" data-src="../data/{session}.json" data-base="../" data-root="{SITE_URL}"></script>')
                page = page.replace("<title>Albany Bill Tracker</title>",
                                    '<title>Watchlist · Albany Bill Tracker</title>\n<meta name="abt-preset" content="{&quot;watch&quot;: true}">', 1)
                os.makedirs(os.path.join(GITHUB, "watchlist"), exist_ok=True)
                with open(os.path.join(GITHUB, "watchlist", "index.html"), "w") as f:
                    f.write(github_page(page))
                # A shared last name gets a page for picking the right person, e.g. /ramos/.
                by_last = defaultdict(list)
                for leg in data.get("legislators", []):
                    by_last[name_key(leg["name"]).split()[-1]].append(leg)
                for last, legs in by_last.items():
                    if len(legs) > 1:
                        os.makedirs(os.path.join(GITHUB, last), exist_ok=True)
                        with open(os.path.join(GITHUB, last, "index.html"), "w") as f:
                            f.write(choose_page(legs))
                print(f"   {len(data.get('legislators', []))} legislator pages")
        else:
            out = os.path.join(SITE, f"{session}.html")
            # A Claude artifact page can't be larger than 16 MB.
            size = len(html.encode("utf-8"))
            if size > 16_000_000:
                raise SystemExit(f"{out} is {size / 1e6:.1f} MB, over the 16 MB page limit")
            if size > 15_300_000:
                print(f"   warning: {out} is {size / 1e6:.1f} MB, close to the 16 MB page limit")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as f:
            f.write(html)
        stages = Counter(r["stage"] for r in recs)
        reintro = sum(1 for i in range(len(recs)) if any(k[0] < session for k in hist[session][i]))
        print(f"{session}: {len(recs)} bills, {reintro} with earlier versions, "
              f"{sum(1 for r in recs if not r['topics'])} untagged, {os.path.getsize(out) / 1e6:.1f} MB -> {out}")
        print("   stages:", {STAGE_LABEL[k]: stages[k] for k in sorted(stages)}, "delegation:", names)


if __name__ == "__main__":
    main()
