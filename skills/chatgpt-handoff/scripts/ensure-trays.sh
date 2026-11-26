#!/usr/bin/env bash
# Create owned remote trays for chatgpt-handoff (idempotent).
set -euo pipefail

TRAYS=(to-chatgpt from-chatgpt)

if ! command -v tray >/dev/null 2>&1; then
  echo "tray: not on PATH" >&2
  exit 1
fi

status_json="$(tray status --format json 2>/dev/null || true)"
signed="$(printf '%s' "$status_json" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("yes" if d.get("signed_in") else "no")' 2>/dev/null || echo no)"
if [ "$signed" != "yes" ]; then
  echo "Not signed in to tray. Run: tray login" >&2
  exit 1
fi

existing_names="$(tray ls --remote --format json 2>/dev/null | python3 -c '
import sys, json
raw = sys.stdin.read().strip() or "[]"
data = json.loads(raw)
names = set()
if isinstance(data, list):
    for row in data:
        if isinstance(row, dict):
            for k in ("name", "title", "label", "tray"):
                v = row.get(k)
                if isinstance(v, str) and v:
                    names.add(v)
                    if " " in v:
                        names.add(v.split()[-1])
elif isinstance(data, dict):
    for row in data.get("trays", data.get("items", [])):
        if isinstance(row, dict) and row.get("name"):
            names.add(row["name"])
print("\n".join(sorted(names)))
' 2>/dev/null || true)"

for name in "${TRAYS[@]}"; do
  if printf '%s\n' "$existing_names" | grep -qx "$name"; then
    echo "ok: remote tray already exists: $name"
    continue
  fi
  if out="$(tray create "$name" --format json 2>&1)"; then
    echo "created: $name"
  else
    if tray ls --remote --format json 2>/dev/null | grep -q "$name"; then
      echo "ok: remote tray already exists: $name"
    else
      echo "failed to ensure tray: $name" >&2
      echo "$out" >&2
      exit 1
    fi
  fi
done

echo "chatgpt-handoff remote trays ready."
