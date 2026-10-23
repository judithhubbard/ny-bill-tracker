#!/usr/bin/env python3
"""New York place names and the counties they're in, from the U.S. Geological Survey's Geographic Names
Information System (towns, cities, villages, hamlets and census places). Writes data/ny_places.json:
{"caughdenoy": ["Oswego"], "lansing": ["Oswego", "Tompkins"], ...}. A name can be in several counties.
The build uses it to tell which county a bill about a named place is about.

Also writes data/district_counties.json from the Census Bureau's district-to-county relationship files
(current Senate and Assembly districts): {"Tompkins": {"S": [[52, 100]], "A": [[125, 100]]}, ...}, each
district with the percent of the county's land in it, largest first. Slivers under 1% are left out.

Usage: python3 fetch_places.py"""
import csv, io, json, os, re, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_NY_Text.zip"
KINDS = {"Populated Place", "Civil", "Census"}
REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/cd-sld"


def main():
    with urllib.request.urlopen(URL, timeout=300) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    name = next(n for n in z.namelist() if n.endswith(".txt"))
    rows = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"), delimiter="|")
    out = {}
    for row in rows:
        if row["state_name"] != "New York" or row["feature_class"] not in KINDS or not row["county_name"]:
            continue
        n = re.sub(r"^(Town|City|Village) of |( County| Census Designated Place| Reservation)$", "", row["feature_name"]).strip()
        counties = out.setdefault(n.lower(), [])
        if row["county_name"] not in counties:
            counties.append(row["county_name"])
    path = os.path.join(HERE, "data", "ny_places.json")
    with open(path, "w") as f:
        json.dump(dict(sorted(out.items())), f, separators=(",", ":"), sort_keys=True)
    print(f"{len(out)} place names -> {path}")

    by_county = {}
    for house, layer in (("S", "sldu"), ("A", "sldl")):
        url = f"{REL}/tab20_{layer}202420_county20_st36.txt"
        with urllib.request.urlopen(url, timeout=120) as r:
            rows = csv.DictReader(io.TextIOWrapper(r, encoding="utf-8-sig"), delimiter="|")
            for row in rows:
                county = row["NAMELSAD_COUNTY_20"].removesuffix(" County")
                part, whole = int(row["AREALAND_PART"] or 0), int(row["AREALAND_COUNTY_20"] or 0)
                district = int(row[next(k for k in row if k.startswith("GEOID_SLD"))][-3:])
                share = round(100 * part / whole) if whole else 0
                if share >= 1 or (part and whole < 100_000_000):  # keep small urban counties' real parts
                    by_county.setdefault(county, {"S": [], "A": []})[house].append([district, max(share, 1)])
    for c in by_county.values():
        for h in c:
            c[h].sort(key=lambda x: -x[1])
    path = os.path.join(HERE, "data", "district_counties.json")
    with open(path, "w") as f:
        json.dump(dict(sorted(by_county.items())), f, separators=(",", ":"))
    print(f"districts for {len(by_county)} counties -> {path}")


if __name__ == "__main__":
    main()
