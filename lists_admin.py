#!/usr/bin/env python3
"""Manage published watchlists: invite codes (one per group) and the lists themselves.

Usage:
  python3 lists_admin.py code-new "Office of Asm. Anna Kelles"   # issue a code for a group
  python3 lists_admin.py codes                                   # list codes and their groups
  python3 lists_admin.py code-revoke <code>                      # revoke a code (hides that group's lists)
  python3 lists_admin.py lists                                   # list published lists
  python3 lists_admin.py list-delete <slug>                      # take a list down

The admin token is read from LISTS_ADMIN_TOKEN, or else ~/.albany_lists_admin. It is never printed."""
import json, os, sys, urllib.request

API = "https://albany-lists.lists-worker.workers.dev"


def token():
    t = os.environ.get("LISTS_ADMIN_TOKEN") or open(os.path.expanduser("~/.albany_lists_admin")).read().strip()
    if not t:
        raise SystemExit("No admin token.")
    return t


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json",
                                          "User-Agent": "albany-lists-admin"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{e.code}: {json.loads(e.read() or b'{}').get('error', e.reason)}")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    if cmd == "code-new" and len(args) == 2:
        r = call("POST", "/admin/codes", {"group": args[1]})
        print(f"Invite code for {r['group']}: {r['code']}")
    elif cmd == "codes":
        for c in sorted(call("GET", "/admin/codes"), key=lambda c: c["created"]):
            print(f"{c['code']}  {'active ' if c['active'] else 'REVOKED'}  {c['group']}  (issued {c['created'][:10]})")
    elif cmd == "code-revoke" and len(args) == 2:
        r = call("DELETE", f"/admin/codes/{args[1]}")
        print(f"Revoked {r['revoked']} ({r['group']}); its lists are now hidden.")
    elif cmd == "lists":
        for l in sorted(call("GET", "/admin/lists"), key=lambda l: l["updated"], reverse=True):
            print(f"{l['slug']}  “{l['title']}”  {l['group']}  {l['bills']} bills  updated {l['updated'][:10]}")
    elif cmd == "list-delete" and len(args) == 2:
        print(f"Deleted {call('DELETE', f'/admin/lists/{args[1]}')['deleted']}.")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
