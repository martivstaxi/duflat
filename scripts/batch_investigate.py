"""Batch flow analysis: read top100_unlabeled.json, for each address pull
NOT transfer history (5 pages = up to 500 events) and compute per-CEX
inflow/outflow shares. Emit a single CSV-style report so we can pick out
hidden CEX wallets in one pass."""
import json, os, sys, time, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
from investigate_wallet import (
    JETTON, LABELS_JSON, load_key, to_uq, http, fetch_jetton_history,
)

INPUT  = r"C:\Users\livea\duflat\scripts\top100_unlabeled.json"
OUTPUT = r"C:\Users\livea\duflat\scripts\batch_flow_report.json"
PAGES  = 5  # up to 500 NOT transfer events per address


def analyze(addr, key, labels):
    self_uq = to_uq(addr) if (addr.startswith("0:") or addr.startswith("-1:")) else addr
    try:
        events = fetch_jetton_history(addr, key, pages=PAGES)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}

    sent_to    = {}
    received_from = {}
    for ev in events:
        for action in ev.get("actions", []):
            if action.get("type") != "JettonTransfer":
                continue
            jt = action.get("JettonTransfer") or {}
            sender    = (jt.get("sender")    or {}).get("address") or ""
            recipient = (jt.get("recipient") or {}).get("address") or ""
            amount    = int(jt.get("amount") or 0)
            sender_uq    = to_uq(sender)    if sender    else ""
            recipient_uq = to_uq(recipient) if recipient else ""
            if sender_uq == self_uq and recipient_uq:
                d = sent_to.setdefault(recipient_uq, {"count":0,"amount":0})
                d["count"]  += 1
                d["amount"] += amount
            elif recipient_uq == self_uq and sender_uq:
                d = received_from.setdefault(sender_uq, {"count":0,"amount":0})
                d["count"]  += 1
                d["amount"] += amount

    total_in  = sum(v["amount"] for v in received_from.values()) or 1
    total_out = sum(v["amount"] for v in sent_to.values()) or 1

    # per-CEX rollup (using LABELS map for known CEX addresses)
    def cex_rollup(side):
        out = {}
        for a, v in side.items():
            lab = labels.get(a, {})
            if lab.get("kind") == "cex":
                # group by exchange family (strip trailing numbers like "Binance Hot Wallet 2")
                name = lab.get("name", "")
                fam = name.split()[0] if name else "?"
                d = out.setdefault(fam, {"amount":0, "count":0})
                d["amount"] += v["amount"]
                d["count"]  += v["count"]
        return out

    in_cex_by_fam  = cex_rollup(received_from)
    out_cex_by_fam = cex_rollup(sent_to)

    # find dominant CEX family on each side
    def top_fam(rollup, total):
        if not rollup:
            return None, 0
        fam, d = max(rollup.items(), key=lambda kv: kv[1]["amount"])
        return fam, d["amount"] / total * 100

    in_top_fam,  in_top_pct  = top_fam(in_cex_by_fam,  total_in)
    out_top_fam, out_top_pct = top_fam(out_cex_by_fam, total_out)
    cex_in_pct  = sum(d["amount"] for d in in_cex_by_fam.values())  / total_in  * 100
    cex_out_pct = sum(d["amount"] for d in out_cex_by_fam.values()) / total_out * 100

    return {
        "events": len(events),
        "in_unique":  len(received_from),
        "out_unique": len(sent_to),
        "total_in_NOT":  total_in / 1e9,
        "total_out_NOT": total_out / 1e9,
        "cex_in_pct":  round(cex_in_pct, 1),
        "cex_out_pct": round(cex_out_pct, 1),
        "in_top_fam":  in_top_fam,
        "in_top_pct":  round(in_top_pct, 1),
        "out_top_fam": out_top_fam,
        "out_top_pct": round(out_top_pct, 1),
    }


def verdict(r):
    """Heuristic from the selling-domain-dogs.ton precedent: 80%+ flow to
    a single CEX family on at least one side = CEX-controlled."""
    if "error" in r:
        return "ERROR"
    if r["events"] == 0:
        return "no-history"
    # single-CEX dominance both sides → very strong (internal/sub-wallet)
    if r["in_top_fam"] and r["out_top_fam"] and r["in_top_fam"] == r["out_top_fam"]:
        if r["in_top_pct"] >= 70 and r["out_top_pct"] >= 70:
            return f"CEX:{r['in_top_fam']} (internal)"
    # 80%+ outflow to one CEX → likely deposit wallet
    if r["out_top_pct"] >= 80:
        return f"CEX:{r['out_top_fam']} (deposit)"
    # 80%+ inflow from one CEX → withdrawal recipient (could be user or sub)
    if r["in_top_pct"] >= 80 and r["out_unique"] < 5:
        return f"CEX:{r['in_top_fam']} (sub/cold)"
    # mixed CEX dominant both sides
    if r["cex_in_pct"] >= 70 and r["cex_out_pct"] >= 70:
        return "CEX (mixed family)"
    if r["events"] < 5:
        return "low-activity"
    return "user/trader"


def main():
    key = load_key()
    labels = json.load(open(LABELS_JSON, encoding="utf-8"))
    holders = json.load(open(INPUT, encoding="utf-8"))
    unlabeled = [h for h in holders if not h["labeled"]]
    print(f"Analyzing {len(unlabeled)} unlabeled holders, {PAGES} pages each\n")

    results = []
    for i, h in enumerate(unlabeled, 1):
        addr = h["address"]
        r = analyze(addr, key, labels)
        v = verdict(r)
        h2 = {**h, "flow": r, "verdict": v}
        results.append(h2)
        if "error" in r:
            print(f"[{i:>2}/{len(unlabeled)}] rank#{h['rank']:<3} {addr[:30]}...  ERR {r['error']}")
        else:
            print(
                f"[{i:>2}/{len(unlabeled)}] rank#{h['rank']:<3} ev={r['events']:<4} "
                f"in:{r['cex_in_pct']:>5.1f}%CEX[{r['in_top_fam'] or '-'}:{r['in_top_pct']:>5.1f}%] "
                f"out:{r['cex_out_pct']:>5.1f}%CEX[{r['out_top_fam'] or '-'}:{r['out_top_pct']:>5.1f}%] "
                f"=> {v}"
            )
        time.sleep(0.1)

    json.dump(results, open(OUTPUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nsaved -> {OUTPUT}")

    # summary
    print("\n=== VERDICT SUMMARY ===")
    from collections import Counter
    c = Counter(r["verdict"] for r in results)
    for v, n in c.most_common():
        print(f"  {n:>3}  {v}")

    print("\n=== CEX CANDIDATES (verdict starts with CEX) ===")
    for r in results:
        if r["verdict"].startswith("CEX"):
            print(f"  rank#{r['rank']:<3} bal={r['balance_NOT']:>14,.0f}  {r['address']}  => {r['verdict']}")


if __name__ == "__main__":
    main()
