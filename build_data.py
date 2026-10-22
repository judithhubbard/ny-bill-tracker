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

    for b in bills.values():
        for s in b["sameAs"]:
            union(b["printNo"], s)
        if b["substitutedBy"]:
            union(b["printNo"], b["substitutedBy"])

    groups = {}
    for p in bills:
        groups.setdefault(find(p), []).append(bills[p])

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
                m = re.match(r"VETOED MEMO\.(\d+)", a["text"])
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
            when(lambda t: t.startswith("VETOED MEMO")),
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
            k = name_key(n)
            return bool(k) and (k == p["key"] or (k.split()[-1] == last(p) and counts[last(p)] == 1))
        found = [(c["name"], same(c.get("chair") or "")) for c in src.values() if any(same(m) for m in c.get("members", []))]
        return [{"name": n.replace(" And ", " and "), "chair": ch} for n, ch in sorted(found, key=lambda x: (not x[1], x[0]))]
    counts = Counter(last(p) for p in seats.values())
    out = []
    for seat, p in sorted(seats.items(), key=lambda kv: kv[1]["key"].split()[-1]):
        house, district = seat.split(":")
        slug = last(p) if counts[last(p)] == 1 else p["key"].replace(" ", "-")
        out.append({"id": seat, "slug": slug, "name": p["name"], "title": "Sen." if house == "S" else "Asm.",
                    "house": house, "district": int(district), "email": p.get("email"), "phone": p.get("phone"),
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
            return {"url": p["url"], "email": p["email"], "phone": p["phone"]}
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
    return {"fetched": raw.get("fetched"), "committees": committees, "people": people, "reps": reps}


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
                    # Session not downloaded: list its bill numbers together, without an outcome.
                    e = hist[s][i].setdefault((ps, None), [ps, "", -1, 0, 0])
                    e[1] = " / ".join(sorted(filter(None, e[1].split(" / ") + [pp]), key=lambda n: n[0] != "S"))

    summary = {s: outcomes(loaded[s][0]) for s in SESSIONS}
    current = max(SESSIONS)

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
                         S(r["program"]), S(r["law"]), vers, int((r["first"] or str(session))[:4]), h,
                         [d.replace("-", "") for d in [r["first"] or ""] + r["keyDates"]]])

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
            # Date of the last floor vote in either house this session.
            "lastVote": max((d for r in recs for i in (1, 2) for d in r["keyDates"][i].split(";")), default=""),
            "strings": strings,
            "rows": rows,
        }
        if session == current:
            data["contacts"] = contacts_for(session, recs, names)
            data["legislators"] = legislators(session)
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
            html = github_page(template.replace(marker, f'<script type="application/json" id="bill-data" data-src="data/{session}.json"></script>'))
            if session == current:
                for leg in data.get("legislators", []):
                    page = template.replace(marker, f'<script type="application/json" id="bill-data" data-src="../data/{session}.json" data-base="../"></script>')
                    preset = json.dumps({"who": leg["id"]}).replace('"', "&quot;")
                    page = page.replace("<title>Albany Bill Tracker</title>",
                                        f'<title>{leg["title"]} {leg["name"]} · Albany Bill Tracker</title>\n<meta name="abt-preset" content="{preset}">', 1)
                    os.makedirs(os.path.join(GITHUB, leg["slug"]), exist_ok=True)
                    with open(os.path.join(GITHUB, leg["slug"], "index.html"), "w") as f:
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
