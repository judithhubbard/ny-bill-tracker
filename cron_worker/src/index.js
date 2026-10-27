// Albany Bill Tracker: starts the GitHub "Update bill tracker" workflow on time.
//
// GitHub's own scheduled runs often start an hour or more late, and some are skipped. Cloudflare's
// timer fires every hour at :05; this decides (in New York time) whether an update is due, then asks
// GitHub to run the workflow now. GitHub's schedule in update.yml stays as a backup.
//
// GITHUB_TOKEN is a secret (wrangler secret put GITHUB_TOKEN < ~/.albany_cron_token): a
// fine-grained token for judithhubbard/ny-bill-tracker with only "Actions: read and write".

const WORKFLOW_URL =
  "https://api.github.com/repos/judithhubbard/ny-bill-tracker/actions/workflows/update.yml/dispatches";

// Same times as update.yml, in Eastern time:
//   every day at 6 a.m.;
//   January-June, weekdays, every hour from 8 a.m. to 7 p.m. (agendas, floor votes);
//   July-December, weekdays, every two hours from 9 a.m. to 7 p.m. (the governor's requests and actions).
function due(now) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", hourCycle: "h23", month: "numeric", hour: "numeric", weekday: "short",
    }).formatToParts(now).map((x) => [x.type, x.value]),
  );
  const month = +p.month, hour = +p.hour, weekday = !["Sat", "Sun"].includes(p.weekday);
  if (hour === 6) return true;
  if (!weekday) return false;
  if (month <= 6) return hour >= 8 && hour <= 19;
  return hour >= 9 && hour <= 19 && hour % 2 === 1;
}

async function startUpdate(env) {
  const r = await fetch(WORKFLOW_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "albany-cron",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    // "timed" makes the run behave like a scheduled one: it publishes only if something changed.
    body: JSON.stringify({ ref: "main", inputs: { timed: "true" } }),
  });
  if (!r.ok) throw new Error(`GitHub said ${r.status}: ${(await r.text()).slice(0, 300)}`);
}

export default {
  async scheduled(event, env) {
    if (due(new Date(event.scheduledTime))) await startUpdate(env);
  },
};
