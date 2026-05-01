"""Diff two daily snapshots (today vs yesterday). Computes:
- new wallets (in today, not in yesterday): count + total balance
- exited wallets (in yesterday, dropped from today): count + total balance
- per-wallet balance delta (limited to top changers)
- net delta (new - exited)
Outputs flow_reports/diff_YYYY-MM-DD.json (date = today's snapshot)."""
import json, os, sys
from datetime import datetime, timezone, timedelta

SNAP_DIR  = r"C:\Users\livea\duflat\snapshots"
OUT_DIR   = r"C:\Users\livea\duflat\flow_reports"
TOP_N     = 50  # how many top changers to keep in the diff


def load_snap(date):
    p = os.path.join(SNAP_DIR, f"{date}.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def main():
    if len(sys.argv) > 1:
        today_date = sys.argv[1]
    else:
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_date = (
        datetime.strptime(today_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        - timedelta(days=1)
    ).strftime("%Y-%m-%d")

    today = load_snap(today_date)
    yest  = load_snap(yesterday_date)
    if not today:
        print(f"no snapshot for {today_date}", file=sys.stderr)
        return 1
    if not yest:
        print(f"no snapshot for {yesterday_date} — nothing to diff (first run?)")
        # still write a stub report so analiz.html has something
        os.makedirs(OUT_DIR, exist_ok=True)
        out_path = os.path.join(OUT_DIR, f"diff_{today_date}.json")
        json.dump({
            "today": today_date, "yesterday": yesterday_date,
            "first_run": True,
            "today_holders": today["total_holders"],
            "today_total_NOT": today["total_NOT"],
        }, open(out_path, "w", encoding="utf-8"), separators=(",", ":"))
        print(f"saved stub -> {out_path}")
        return 0

    today_map = {h["addr"]: h for h in today["holders"]}
    yest_map  = {h["addr"]: h for h in yest["holders"]}

    new_addrs    = [a for a in today_map if a not in yest_map]
    exited_addrs = [a for a in yest_map  if a not in today_map]

    new_total_NOT    = round(sum(today_map[a]["balance"] for a in new_addrs), 2)
    exited_total_NOT = round(sum(yest_map[a]["balance"]  for a in exited_addrs), 2)

    # per-wallet delta for addresses present in both snapshots
    deltas = []
    for a, h in today_map.items():
        if a in yest_map:
            d = h["balance"] - yest_map[a]["balance"]
            if abs(d) >= 1:  # ignore noise below 1 NOT
                deltas.append({"addr": a, "delta": round(d, 2),
                               "today": h["balance"], "yesterday": yest_map[a]["balance"]})
    deltas.sort(key=lambda x: -abs(x["delta"]))

    report = {
        "today":     today_date,
        "yesterday": yesterday_date,
        "today_holders":     today["total_holders"],
        "yesterday_holders": yest["total_holders"],
        "today_total_NOT":     today["total_NOT"],
        "yesterday_total_NOT": yest["total_NOT"],
        "delta_total_NOT":   round(today["total_NOT"] - yest["total_NOT"], 2),
        "new_wallets":     {"count": len(new_addrs),    "total_NOT": new_total_NOT},
        "exited_wallets":  {"count": len(exited_addrs), "total_NOT": exited_total_NOT},
        "net_wallet_count":  len(new_addrs) - len(exited_addrs),
        "net_wallet_NOT":    round(new_total_NOT - exited_total_NOT, 2),
        "top_gainers": [d for d in deltas if d["delta"] > 0][:TOP_N],
        "top_losers":  [d for d in deltas if d["delta"] < 0][:TOP_N],
        "new_addrs_sample":    [{"addr": a, "balance": today_map[a]["balance"], "rank": today_map[a]["rank"]}
                                for a in sorted(new_addrs, key=lambda x: -today_map[x]["balance"])[:TOP_N]],
        "exited_addrs_sample": [{"addr": a, "balance": yest_map[a]["balance"], "rank": yest_map[a]["rank"]}
                                for a in sorted(exited_addrs, key=lambda x: -yest_map[x]["balance"])[:TOP_N]],
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"diff_{today_date}.json")
    json.dump(report, open(out_path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    print(f"saved -> {out_path}")

    print(f"\n=== DIFF: {yesterday_date} -> {today_date} ===")
    print(f"  holders:    {yest['total_holders']:>5} -> {today['total_holders']:>5}  ({today['total_holders']-yest['total_holders']:+})")
    print(f"  total NOT:  {yest['total_NOT']:>14,.0f} -> {today['total_NOT']:>14,.0f}  ({report['delta_total_NOT']:+,.0f})")
    print(f"  new:        {report['new_wallets']['count']:>5} wallets   ({new_total_NOT:>14,.0f} NOT)")
    print(f"  exited:     {report['exited_wallets']['count']:>5} wallets   ({exited_total_NOT:>14,.0f} NOT)")
    print(f"  net wallet count: {report['net_wallet_count']:+}")
    print(f"  net wallet NOT  : {report['net_wallet_NOT']:+,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
