"""Combine cex_flow + diff into one daily report file.
Output: flow_reports/report_YYYY-MM-DD.json
And updates flow_reports/latest.json (pointer to the latest report).
Also maintains flow_reports/index.json (list of all report dates)."""
import json, os, sys
from datetime import datetime, timezone

DIR = r"C:\Users\livea\duflat\flow_reports"


def main():
    if len(sys.argv) > 1:
        date = sys.argv[1]
    else:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    cex_path  = os.path.join(DIR, f"cex_flow_{date}.json")
    diff_path = os.path.join(DIR, f"diff_{date}.json")
    out_path  = os.path.join(DIR, f"report_{date}.json")

    cex  = json.load(open(cex_path,  encoding="utf-8")) if os.path.exists(cex_path)  else None
    diff = json.load(open(diff_path, encoding="utf-8")) if os.path.exists(diff_path) else None

    if not cex and not diff:
        print(f"no inputs for {date}", file=sys.stderr)
        return 1

    # strip per_wallet detail from cex_flow for the lightweight report — keep it
    # only in the original file. report carries the rollups and totals.
    cex_summary = None
    if cex:
        cex_summary = {k: v for k, v in cex.items() if k != "per_wallet"}

    report = {
        "date":      date,
        "generated": datetime.now(timezone.utc).isoformat(),
        "cex_flow":  cex_summary,
        "diff":      diff,
    }
    json.dump(report, open(out_path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    print(f"saved -> {out_path}")

    # update latest.json (lightweight pointer)
    latest_path = os.path.join(DIR, "latest.json")
    json.dump(report, open(latest_path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    print(f"updated -> {latest_path}")

    # rebuild index.json (list of dates)
    dates = sorted({
        f[len("report_"):-len(".json")]
        for f in os.listdir(DIR)
        if f.startswith("report_") and f.endswith(".json")
    })
    index = {"dates": dates, "latest": dates[-1] if dates else None}
    index_path = os.path.join(DIR, "index.json")
    json.dump(index, open(index_path, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"updated -> {index_path} ({len(dates)} reports)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
