# Albany Bill Tracker

Every New York Senate and Assembly bill, paired across the two houses, with filters by
stage, topic, law amended, committee, and history in earlier and later sessions.
Published at https://judithhubbard.github.io/ny-bill-tracker/ and rebuilt every morning.

Data: New York State Senate [Open Legislation API](https://legislation.nysenate.gov/).

## How it works

- `fetch_bills.py SESSION` downloads every bill in a session (about 4 minutes) to `data/bills_SESSION.json`.
- `build_data.py --github _site` builds one page per session with the data embedded:
  `index.html` for the current session and `YEAR.html` for past ones.
- `fetch_contacts.py SESSION` collects email, district phone and page for every legislator (Open States), committee chairs, members and meeting times (Senate from the API,
  Assembly from nyassembly.gov) and legislators' page links into `data/contacts_SESSION.json`, used for
  the "What's next and who to contact" box under each bill.
- `fetch_party_history.py` (run by hand; rarely changes) records the party of every current and
  former legislator by seat, from the Open States people archive, into `data/seat_parties.json`,
  so party comparisons cover past sessions too.
- `fetch_agendas.py SESSION` downloads Senate committee agendas (which bills each committee takes
  up, and when) into `data/agendas_SESSION.json`, so bills show an upcoming committee meeting.
  The Assembly doesn't publish agendas through the API.
- `fetch_old_outcomes.py` (run once) saves how far each 2009–2015 bill got into
  `data/old_outcomes.json.gz`, so bill histories show outcomes before the full downloads begin.
- On GitHub Pages each current legislator also has a page filtered to their bills, at
  `/<last name>/` (or `/<first>-<last>/` when a last name is shared, with `/<last name>/` then
  offering a choice). The list comes from the nightly contacts refresh, so it follows elections.
- The Watchlist tab (also `/watchlist/`) shows the visitor's starred bills, each marked Support or
  Oppose, with a "What to do" list grouped by person and email drafts. Watchlists are kept in each
  browser (localStorage); the share link (`/watchlist/#w=2025.S1234.-A5678`, "-" = oppose) carries a copy.
- Floor leaders (Senate Majority Leader, Assembly Speaker) are set in `LEADERS` in
  `build_data.py`; check them after leadership votes each January of odd years.
- Votes: Senate floor and committee votes come from the API; Assembly floor votes from
  nyassembly.gov via `fetch_assembly_votes.py`, cached in `data/assembly_votes_SESSION.json`.
- A bill's own link is the page address plus `#S1234` (or `#A1234`).
- `tracker.html` is the page template; topic rules and the sponsor checkboxes are at the top of `build_data.py`.
- `.github/workflows/update.yml` runs both every day and deploys to GitHub Pages. The note at
  the top of the page (end of votes, governor's remaining bills, session over) is worked out
  in the browser from the data and the date, so it changes on its own.
  The API key is the repository secret `NYSENATE_API_KEY`.

Past sessions don't change, so they're stored compressed in `data/` and not re-downloaded.

## When a new session starts (January of odd years)

Nothing has to be done by hand. The workflow works out the session from the date. The first
time it runs in a new session, it downloads the session that just ended one last time and
commits it as `data/bills_YEAR.json.gz`. Until the new session has bills, the old one stays
the current page. The Webb and Kelles checkboxes carry forward for Senate District 52 and
Assembly District 125, and drop out on their own if someone else holds either seat
(`DELEGATION` in `build_data.py`).
