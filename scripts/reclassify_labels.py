"""Re-classify the existing exchanges.json without hitting tonapi.io."""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from discover_cex import classify, OUT_JSON, OUT_JS, MANUAL_OVERRIDES

with open(OUT_JSON, encoding="utf-8") as f:
    labels = json.load(f)

# auto-classify
counts = {"cex": 0, "protocol": 0, "named": 0}
for addr, meta in labels.items():
    meta["kind"] = classify(meta.get("name", ""))

# apply manual overrides (wins over auto)
for addr, override in MANUAL_OVERRIDES.items():
    labels[addr] = {**labels.get(addr, {}), **override}

for meta in labels.values():
    counts[meta["kind"]] += 1
print(f"{len(labels)} labeled  |  cex={counts['cex']}  protocol={counts['protocol']}  named={counts['named']}")
print(f"manual overrides applied: {len(MANUAL_OVERRIDES)}")

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(labels, f, indent=2, ensure_ascii=False)

items = sorted(labels.items(), key=lambda kv: (kv[1]["kind"], kv[1]["name"].lower()))
lines = ["const LABELS = {"]
last_kind = None
for addr, meta in items:
    if meta["kind"] != last_kind:
        lines.append(f"  // {meta['kind']}")
        last_kind = meta["kind"]
    name_js = json.dumps(meta["name"])
    lines.append(f'  "{addr}": {{ name: {name_js}, kind: "{meta["kind"]}" }},')
lines.append("};")
with open(OUT_JS, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"saved -> {OUT_JS}")
