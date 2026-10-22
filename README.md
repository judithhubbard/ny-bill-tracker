# Albany Bill Tracker

Every New York Senate and Assembly bill, paired across the two houses, with filters by
stage, topic, law amended, committee, and history in earlier and later sessions.
Published at https://judithhubbard.github.io/ny-bill-tracker/ and rebuilt every morning.

Data: New York State Senate [Open Legislation API](https://legislation.nysenate.gov/).

## How it works

- `fetch_bills.py SESSION` downloads every bill in a session (about 4 minutes) to `data/bills_SESSION.json`.
- `build_data.py --github _site` builds one page per session with the data embedded:
  `index.html` for the current session and `YEAR.html` for past ones.
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
