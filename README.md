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
- `.github/workflows/update.yml` runs both every day and deploys to GitHub Pages.
  The API key is the repository secret `NYSENATE_API_KEY`.

Past sessions don't change, so they're stored compressed in `data/` and not re-downloaded.

## When a new session starts (January of odd years)

1. Download the finished session one last time and store it:
   `python3 fetch_bills.py 2025 && gzip -9 -k -f data/bills_2025.json`, then commit `data/bills_2025.json.gz`.
2. In `.github/workflows/update.yml`, set `CURRENT_SESSION` to the new year (e.g. `"2027"`).
3. In `build_data.py`, add the new session to `DELEGATION` so the Webb and Kelles checkboxes appear.
