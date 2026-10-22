"""Party of every New York legislator who has held a seat, current and former, from the
Open States people archive (https://github.com/openstates/people, data/ny). Lets the party
comparison cover past sessions. Writes data/seat_parties.json: "S:5" -> list of holders with
last name, years held and party. Past sessions don't change, so this rarely needs a re-run.

Usage: python3 fetch_party_history.py [path to a local copy of openstates/people]"""
import glob, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def unquote(s):
    """A YAML scalar: double-quoted ones may hold escapes like \\xE1 (á)."""
    s = s.strip()
    if s.startswith('"'):
        return s[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
    return s.strip("'")


def parse(text):
    """Just the fields needed from an Open States person file (plain YAML, no library needed)."""
    person, section, item = {"party": [], "roles": []}, None, None
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            section, item = m.group(1), None
            if section in ("family_name", "name"):
                person["last" if section == "family_name" else "name"] = unquote(m.group(2))
            continue
        m = re.match(r"^(- |  )(\w+):\s*'?([^']*)'?$", line)
        if m and section in ("party", "roles"):
            if m.group(1) == "- ":
                item = {}
                person[section].append(item)
            item[m.group(2)] = m.group(3).strip('"')
    return person


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else None
    if not root:
        root = tempfile.mkdtemp()
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/openstates/people.git", root], check=True)
        subprocess.run(["git", "-C", root, "sparse-checkout", "set", "data/ny"], check=True)
    seats = {}
    for path in glob.glob(os.path.join(root, "data/ny/legislature/*.yml")) + glob.glob(os.path.join(root, "data/ny/retired/*.yml")):
        p = parse(open(path, encoding="utf-8").read())
        last = p.get("last") or p.get("name", "").split()[-1]
        for role in p["roles"]:
            if role.get("type") not in ("upper", "lower") or not role.get("district"):
                continue
            start, end = role.get("start_date", "")[:4], role.get("end_date", "")[:4]
            # A role's party: the party entry whose dates overlap it, else the first one listed.
            party = next((x["name"] for x in p["party"]
                          if (not x.get("end_date") or not start or x["end_date"][:4] >= start)
                          and (not x.get("start_date") or not end or x["start_date"][:4] <= end)), "")
            code = "D" if "Democrat" in party else "R" if "Republican" in party else None
            if code:
                seat = ("S" if role["type"] == "upper" else "A") + ":" + str(int(role["district"]))
                seats.setdefault(seat, []).append({"last": last, "name": p.get("name"), "start": start, "end": end, "party": code})
    json.dump(seats, open(os.path.join(HERE, "data", "seat_parties.json"), "w"), indent=0, sort_keys=True)
    print(f"{sum(map(len, seats.values()))} seat holders across {len(seats)} seats")


if __name__ == "__main__":
    main()
