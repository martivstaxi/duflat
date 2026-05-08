// Dispatcher Worker for duflat NOT flow pipeline.
//
// GET  /status   → { last_dispatch, cooldown_remaining_ms }
// POST /dispatch → triggers the GitHub Actions workflow if cooldown elapsed
//
// Bindings (set in wrangler.toml + dashboard):
//   STATE     KV namespace, key "last_dispatch" stores epoch ms
//   GH_TOKEN  secret, GitHub PAT with `workflow` scope on martivstaxi/duflat
//   REPO      env var "martivstaxi/duflat"
//   WORKFLOW  env var "daily-not-flow.yml"
//   ALLOWED_ORIGIN env var "https://duflat.com"

const COOLDOWN_MS = 12 * 60 * 60 * 1000;

function corsHeaders(env, req) {
  const allowed = (env.ALLOWED_ORIGIN || "").split(",").map(s => s.trim()).filter(Boolean);
  const origin  = (req && req.headers.get("Origin")) || "";
  const allow   = allowed.includes(origin) ? origin : (allowed[0] || "*");
  return {
    "Access-Control-Allow-Origin":  allow,
    "Vary":                         "Origin",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age":       "86400",
  };
}

function json(body, status, env, req) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(env, req) },
  });
}

async function readState(env) {
  const last = parseInt((await env.STATE.get("last_dispatch")) || "0", 10);
  const now = Date.now();
  const remaining = Math.max(0, last + COOLDOWN_MS - now);
  return { last, now, remaining };
}

async function dispatchWorkflow(env) {
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}/dispatches`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_TOKEN}`,
      "Accept":        "application/vnd.github+json",
      "Content-Type":  "application/json",
      "User-Agent":    "duflat-dispatcher",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (!r.ok) {
    const detail = await r.text();
    return { ok: false, status: r.status, detail };
  }
  return { ok: true };
}

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(env, req) });
    }

    const { pathname } = new URL(req.url);

    if (req.method === "GET" && pathname === "/status") {
      const { last, remaining } = await readState(env);
      return json({
        last_dispatch:         last || null,
        cooldown_remaining_ms: remaining,
        cooldown_total_ms:     COOLDOWN_MS,
      }, 200, env, req);
    }

    // CORS proxy: /cmc/historical?id=...&convertId=...&timeStart=...&timeEnd=...&interval=1h
    // Allows the static site to fetch CoinMarketCap data-api directly from the browser.
    if (req.method === "GET" && pathname === "/cmc/historical") {
      const u = new URL(req.url);
      const id = u.searchParams.get("id");
      const convertId = u.searchParams.get("convertId") || "2781";
      const timeStart = u.searchParams.get("timeStart");
      const timeEnd = u.searchParams.get("timeEnd");
      const interval = u.searchParams.get("interval") || "1h";
      // Whitelist allowed CMC ids to prevent open proxy abuse
      const ALLOWED_IDS = new Set(["23095", "28850"]); // BONK, NOT
      if (!id || !ALLOWED_IDS.has(id) || !timeStart || !timeEnd) {
        return json({ error: "bad_params" }, 400, env, req);
      }
      const cmcUrl = `https://api.coinmarketcap.com/data-api/v3.1/cryptocurrency/historical?id=${id}&convertId=${convertId}&timeStart=${timeStart}&timeEnd=${timeEnd}&interval=${interval}`;
      try {
        const r = await fetch(cmcUrl, {
          headers: { "User-Agent": "duflat-cmc-proxy", "Accept": "application/json" },
          cf: { cacheTtl: 60, cacheEverything: true },
        });
        if (!r.ok) {
          return json({ error: "cmc_upstream", status: r.status }, 502, env, req);
        }
        const body = await r.text();
        return new Response(body, {
          status: 200,
          headers: { "Content-Type": "application/json", ...corsHeaders(env, req) },
        });
      } catch (e) {
        return json({ error: "cmc_fetch_failed", detail: String(e) }, 502, env, req);
      }
    }

    if (req.method === "POST" && pathname === "/dispatch") {
      const { remaining, now } = await readState(env);
      if (remaining > 0) {
        return json({
          ok: false,
          error: "cooldown",
          cooldown_remaining_ms: remaining,
        }, 429, env, req);
      }

      const result = await dispatchWorkflow(env);
      if (!result.ok) {
        return json({
          ok: false,
          error: "github_dispatch_failed",
          status: result.status,
          detail: result.detail,
        }, 502, env, req);
      }

      // Mark cooldown only on successful dispatch
      await env.STATE.put("last_dispatch", String(now));
      return json({ ok: true, dispatched_at: now }, 200, env, req);
    }

    return json({ error: "not_found", method: req.method, path: pathname }, 404, env, req);
  },
};
