#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-https://leon4gr45-aux-synthetic-ux-demo.hf.space}"
endpoint="${base_url%/}/gradio_api/call/run_contract_demo"
payload='{"data":["https://example.com","Find support information",2,42]}'

curl --version | head -n 1
post_response="$({
  curl -fsS -X POST "$endpoint" \
    -H "Content-Type: application/json" \
    -d "$payload"
})"
event_id="$({
  printf '%s' "$post_response" | python -c \
    'import json, sys; print(json.load(sys.stdin)["event_id"])'
})"
test -n "$event_id"
printf 'Queued event: %s\n' "$event_id"

result_file="$(mktemp)"
trap 'rm -f "$result_file"' EXIT
curl -fsS -N "$endpoint/$event_id" | tee "$result_file"

python - "$result_file" <<'PY'
import json
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
assert "event: complete" in lines, lines
data_line = next(line for line in lines if line.startswith("data: "))
outputs = json.loads(data_line.removeprefix("data: "))
assert len(outputs) == 4, outputs
run = json.loads(outputs[0])
readiness = json.loads(outputs[3])
assert run["mode"] == "offline_contract_demo", run
assert run["verdict"] == "not_executed", run
assert len(run["syntheticUsers"]) == 2, run
assert readiness["demo"] == "ready", readiness
print(f"Validated {run['runId']}: {run['mode']}, demo={readiness['demo']}")
PY
