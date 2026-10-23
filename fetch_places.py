#!/usr/bin/env python3
"""New York place names and the counties they're in, from the U.S. Geological Survey's Geographic Names
Information System (towns, cities, villages, hamlets and census places). Writes data/ny_places.json:
{"caughdenoy": ["Oswego"], "lansing": ["Oswego", "Tompkins"], ...}. A name can be in several counties.
The build uses it to tell which county a bill about a named place is about.

Usage: python3 fetch_places.py"""
import csv, io, json, os, re, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_NY_Text.zip"
KINDS = {"Populated Place", "Civil", "Census"}


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


if __name__ == "__main__":
    main()
