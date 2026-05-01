"""Generate MANUAL_OVERRIDES dict entries for the top1000 batch_flow_report."""
import json

REPORT = r"C:\Users\livea\duflat\scripts\batch_flow_report_top1000.json"
r = json.load(open(REPORT, encoding="utf-8"))

# family normalization
FAM_FIX = {
    "Bitget12":   "Bitget",
    "Wallet":     "Telegram Wallet",  # 'Wallet in Telegram'.split()[0] = 'Wallet'
    "lbank.info": "lbank.info",
}

def norm_fam(f):
    return FAM_FIX.get(f, f)

# verdict suffix
def suffix(v):
    if "internal" in v: return "Internal"
    if "deposit"  in v: return "Deposit"
    return "Cold"  # sub/cold

cex = [x for x in r if x["verdict"].startswith("CEX")]
print(f"# top-1000 batch (rank 101-1000): {len(cex)} hidden CEX wallets")
print()

for x in sorted(cex, key=lambda h: h["rank"]):
    f = x["flow"]
    # pick dominant family — prefer the side with the higher pct
    in_fam, out_fam = f.get("in_top_fam"), f.get("out_top_fam")
    in_pct, out_pct = f.get("in_top_pct", 0), f.get("out_top_pct", 0)
    fam = in_fam if in_pct >= out_pct and in_fam else (out_fam or in_fam or "?")
    fam = norm_fam(fam)
    name = f"{fam} {suffix(x['verdict'])}"
    why = (
        f"rank#{x['rank']}, "
        f"in:{in_pct}%[{norm_fam(in_fam) if in_fam else '-'}]/"
        f"out:{out_pct}%[{norm_fam(out_fam) if out_fam else '-'}], "
        f"ev={f['events']}, bal={x['balance_NOT']/1e6:.1f}M"
    )
    print(f"    # {why}")
    print(f'    "{x["address"]}":')
    print(f'        {{"name": "{name}", "kind": "cex"}},')
