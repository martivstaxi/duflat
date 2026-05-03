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

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin":  env.ALLOWED_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age":       "86400",
  };
}

function json(body, status, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(env) },
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
      return new Response(null, { headers: corsHeaders(env) });
    }

    const { pathname } = new URL(req.url);

    if (req.method === "GET" && pathname === "/status") {
      const { last, remaining } = await readState(env);
      return json({
        last_dispatch:         last || null,
        cooldown_remaining_ms: remaining,
        cooldown_total_ms:     COOLDOWN_MS,
      }, 200, env);
    }

    if (req.method === "POST" && pathname === "/dispatch") {
      const { remaining, now } = await readState(env);
      if (remaining > 0) {
        return json({
          ok: false,
          error: "cooldown",
          cooldown_remaining_ms: remaining,
        }, 429, env);
      }

      const result = await dispatchWorkflow(env);
      if (!result.ok) {
        return json({
          ok: false,
          error: "github_dispatch_failed",
          status: result.status,
          detail: result.detail,
        }, 502, env);
      }

      // Mark cooldown only on successful dispatch
      await env.STATE.put("last_dispatch", String(now));
      return json({ ok: true, dispatched_at: now }, 200, env);
    }

    return json({ error: "not_found", method: req.method, path: pathname }, 404, env);
  },
};
