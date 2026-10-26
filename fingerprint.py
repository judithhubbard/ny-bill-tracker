#!/usr/bin/env python3
"""Prints a fingerprint of a built site, ignoring the time of day in the "updated" stamp on every build.

The workflow compares it with the live site's fingerprint.txt and skips publishing when they match,
so returning visitors don't download the same bill data again just because a run happened. The date
is kept, so the site still publishes at least once a day and its "updated" date never looks stale.

Usage: python3 fingerprint.py SITE_DIR
"""
import hashlib, os, re, sys

STAMP = re.compile(rb"(?<=\d{4}-\d\d-\d\d) \d\d:\d\d ET")
root = sys.argv[1]
h = hashlib.sha256()
for d, dirs, files in sorted(os.walk(root)):
    dirs.sort()
    for name in sorted(files):
        path = os.path.join(d, name)
        if os.path.relpath(path, root) == "fingerprint.txt":
            continue
        h.update(os.path.relpath(path, root).encode() + b"\0")
        h.update(STAMP.sub(b"", open(path, "rb").read()) + b"\0")
print(h.hexdigest())
