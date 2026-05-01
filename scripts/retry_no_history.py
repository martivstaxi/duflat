"""Retry 'no-history' addresses with slower pacing — they may have been
rate-limited (HTTP 429) on the first batch pass."""
import json, os, sys, time, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
from investigate_wallet import LABELS_JSON, load_key, to_uq, fetch_jetton_history
from batch_investigate import analyze, verdict, OUTPUT as REPORT

key = load_key()
labels = json.load(open(LABELS_JSON, encoding="utf-8"))
report = json.load(open(REPORT, encoding="utf-8"))

retry_targets = [r for r in report if r["verdict"] in ("no-history", "low-activity")]
print(f"Retrying {len(retry_targets)} addresses with 2s pacing...\n")

for i, h in enumerate(retry_targets, 1):
    addr = h["address"]
    time.sleep(2.0)  # extra slow
    r = analyze(addr, key, labels)
    v = verdict(r)
    h["flow"] = r
    h["verdict"] = v
    if "error" in r:
        print(f"[{i:>2}/{len(retry_targets)}] rank#{h['rank']:<3}  ERR {r['error']}")
    else:
        print(
            f"[{i:>2}/{len(retry_targets)}] rank#{h['rank']:<3} ev={r['events']:<4} "
            f"in:{r['cex_in_pct']:>5.1f}%[{r['in_top_fam'] or '-'}:{r['in_top_pct']:>5.1f}%] "
            f"out:{r['cex_out_pct']:>5.1f}%[{r['out_top_fam'] or '-'}:{r['out_top_pct']:>5.1f}%] "
            f"=> {v}"
        )

# write merged report back
json.dump(report, open(REPORT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

# new summary
print("\n=== UPDATED VERDICT SUMMARY ===")
from collections import Counter
c = Counter(r["verdict"] for r in report)
for v, n in c.most_common():
    print(f"  {n:>3}  {v}")

print("\n=== ALL CEX CANDIDATES ===")
for r in report:
    if r["verdict"].startswith("CEX"):
        print(f"  rank#{r['rank']:<3} bal={r['balance_NOT']:>14,.0f}  {r['address']}  => {r['verdict']}")
