// Albany Bill Tracker: published watchlists.
//
// Anyone can read a published list. Only holders of an invite code (one per group, issued by the
// site's owner) can create one; whoever creates it gets a private edit key for updating it.
// Revoking a group's code hides that group's lists.
//
// KV keys:  code:<code>  -> { group, active, created }
//           list:<slug>  -> { slug, title, group, code, session, bills, editHash, created, updated }

const ALLOWED_ORIGINS = [
  "https://albanybilltracker.org",
  "https://www.albanybilltracker.org",
  "https://judithhubbard.github.io",
  "http://localhost:8765",
];
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,60}$/;
const BILL_RE = /^-?[SA]\d{1,5}$/; // "-" in front means oppose
const MAX_BILLS = 500;
const MAX_TITLE = 120;

const enc = new TextEncoder();
async function sha256(s) {
  const d = await crypto.subtle.digest("SHA-256", enc.encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function randomToken(n) {
  const alphabet = "abcdefghijkmnpqrstuvwxyz23456789"; // no look-alike characters
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return [...bytes].map((b) => alphabet[b % alphabet.length]).join("");
}
// Compares two strings in constant time, for tokens.
function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function corsHeaders(req) {
  const origin = req.headers.get("Origin");
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Edit-Key, Authorization",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}
const reply = (req, body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...corsHeaders(req) } });
const fail = (req, status, message) => reply(req, { error: message }, status);

// The list fields a client may set, checked.
function cleanList(body) {
  const title = String(body?.title || "").trim().slice(0, MAX_TITLE);
  if (!title) return { error: "The list needs a name." };
  const bills = Array.isArray(body?.bills) ? body.bills.map((b) => String(b).toUpperCase().trim()) : [];
  if (bills.length > MAX_BILLS) return { error: `A list can have at most ${MAX_BILLS} bills.` };
  if (bills.some((b) => !BILL_RE.test(b))) return { error: "Bills must look like S1234 or A1234." };
  const session = Number(body?.session);
  if (!Number.isInteger(session) || session < 2009 || session > 2099 || session % 2 === 0) return { error: "Unknown session." };
  return { title, bills: [...new Set(bills)], session };
}
function slugify(title) {
  return title.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 50) || "list";
}
const publicView = (l) => ({ slug: l.slug, title: l.title, group: l.group, session: l.session, bills: l.bills, updated: l.updated });

async function getJSON(env, key) { return JSON.parse((await env.LISTS.get(key)) || "null"); }
async function codeActive(env, code) { const c = await getJSON(env, `code:${code}`); return c && c.active ? c : null; }

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(req) });
    const url = new URL(req.url);
    const parts = url.pathname.split("/").filter(Boolean);
    try {
      // ---- Admin: the site's owner, with the admin token. ----
      if (parts[0] === "admin") {
        const token = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
        if (!env.ADMIN_TOKEN || !same(token, env.ADMIN_TOKEN)) return fail(req, 401, "Not authorized.");
        if (parts[1] === "codes" && req.method === "POST") {
          const body = await req.json().catch(() => ({}));
          const group = String(body.group || "").trim().slice(0, 100);
          if (!group) return fail(req, 400, "Give the group's name.");
          const code = randomToken(10);
          await env.LISTS.put(`code:${code}`, JSON.stringify({ group, active: true, created: new Date().toISOString() }));
          return reply(req, { code, group });
        }
        if (parts[1] === "codes" && req.method === "GET") {
          const out = [];
          for (const k of (await env.LISTS.list({ prefix: "code:" })).keys) out.push({ code: k.name.slice(5), ...(await getJSON(env, k.name)) });
          return reply(req, out);
        }
        if (parts[1] === "codes" && parts[2] && req.method === "DELETE") {
          const c = await getJSON(env, `code:${parts[2]}`);
          if (!c) return fail(req, 404, "No such code.");
          c.active = false;
          await env.LISTS.put(`code:${parts[2]}`, JSON.stringify(c));
          return reply(req, { revoked: parts[2], group: c.group });
        }
        if (parts[1] === "lists" && req.method === "GET") {
          const out = [];
          for (const k of (await env.LISTS.list({ prefix: "list:" })).keys) {
            const l = await getJSON(env, k.name);
            if (l) out.push({ slug: l.slug, title: l.title, group: l.group, code: l.code, bills: l.bills.length, updated: l.updated });
          }
          return reply(req, out);
        }
        if (parts[1] === "lists" && parts[2] && req.method === "DELETE") {
          await env.LISTS.delete(`list:${parts[2]}`);
          return reply(req, { deleted: parts[2] });
        }
        return fail(req, 404, "Unknown admin request.");
      }

      if (parts[0] !== "lists") return fail(req, 404, "Not found.");
      const slug = parts[1];

      // ---- Read a list: anyone. ----
      if (slug && req.method === "GET") {
        if (!SLUG_RE.test(slug)) return fail(req, 404, "No such list.");
        const l = await getJSON(env, `list:${slug}`);
        if (!l || !(await codeActive(env, l.code))) return fail(req, 404, "This list isn't available.");
        return reply(req, publicView(l));
      }

      // ---- Create a list: needs an active invite code. ----
      if (!slug && req.method === "POST") {
        const body = await req.json().catch(() => null);
        const code = String(body?.code || "").trim().toLowerCase();
        const c = code && (await codeActive(env, code));
        if (!c) return fail(req, 403, "That invite code isn't valid.");
        const fields = cleanList(body);
        if (fields.error) return fail(req, 400, fields.error);
        let base = slugify(fields.title), s = base, n = 2;
        while (await env.LISTS.get(`list:${s}`)) s = `${base}-${n++}`;
        const editKey = randomToken(24), now = new Date().toISOString();
        await env.LISTS.put(`list:${s}`, JSON.stringify({ slug: s, ...fields, group: c.group, code, editHash: await sha256(editKey), created: now, updated: now }));
        return reply(req, { slug: s, editKey, group: c.group }, 201);
      }

      // ---- Update or delete a list: needs its edit key, and its group's code still active. ----
      if (slug && (req.method === "PUT" || req.method === "DELETE")) {
        const l = SLUG_RE.test(slug) && (await getJSON(env, `list:${slug}`));
        if (!l) return fail(req, 404, "No such list.");
        if (!same(await sha256(req.headers.get("X-Edit-Key") || ""), l.editHash)) return fail(req, 403, "That edit key doesn't match this list.");
        if (!(await codeActive(env, l.code))) return fail(req, 403, "This group's invite code has been revoked.");
        if (req.method === "DELETE") { await env.LISTS.delete(`list:${slug}`); return reply(req, { deleted: slug }); }
        const fields = cleanList(await req.json().catch(() => null));
        if (fields.error) return fail(req, 400, fields.error);
        Object.assign(l, fields, { updated: new Date().toISOString() });
        await env.LISTS.put(`list:${slug}`, JSON.stringify(l));
        return reply(req, publicView(l));
      }
      return fail(req, 405, "Not allowed.");
    } catch (e) {
      return fail(req, 500, "Something went wrong.");
    }
  },
};
