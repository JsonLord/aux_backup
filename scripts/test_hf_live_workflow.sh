#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-https://leon4gr45-aux-synthetic-ux-demo.hf.space}"
: "${HF_OAUTH_TOKEN:?Set HF_OAUTH_TOKEN to a Hugging Face OAuth or personal access token}"
: "${WORKSPACE_ID:?Set WORKSPACE_ID to an allowed hf:user:* or hf:org:* workspace}"

curl --version | head -n 1
curl -fsS "${base_url%/}/api/readiness" | python -m json.tool

result="$(mktemp)"
job_result="$(mktemp)"
artifacts_result="${result}.artifacts"
trap 'rm -f "$result" "$job_result" "$artifacts_result"' EXIT
curl -fsS -X POST "${base_url%/}/api/v1/workflows/usability" \
  -H "Authorization: Bearer ${HF_OAUTH_TOKEN}" \
  -H "X-Workspace-ID: ${WORKSPACE_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "OpenDesign usability acceptance",
    "theme": "Open-source AI design workflow",
    "customer_profile": "Designers and frontend developers evaluating an open-source Claude design alternative",
    "persona_count": 5,
    "seed": 20260827,
    "allow_offline_fallback": true,
    "url": "https://open-design.ai/",
    "tasks": [
      "Understand OpenDesign and its primary value proposition",
      "Find how to start using or installing OpenDesign",
      "Inspect examples, documentation, or source code",
      "Identify pricing, licensing, or usage constraints",
      "Locate support, community, or contact information"
    ]
  }' | tee "$result"

read -r SESSION_ID JOB_ID < <(python - "$result" <<'PY'
import json, sys
result = json.load(open(sys.argv[1]))
print(result["session"]["session_id"], result["job"]["job_id"])
PY
)

for _ in $(seq 1 180); do
  curl -fsS "${base_url%/}/api/v1/jobs/${JOB_ID}" \
    -H "Authorization: Bearer ${HF_OAUTH_TOKEN}" \
    -H "X-Workspace-ID: ${WORKSPACE_ID}" >"$job_result"
  status="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$job_result")"
  [[ "$status" =~ ^(succeeded|failed|cancelled)$ ]] && break
  sleep 5
done

curl -fsS "${base_url%/}/api/v1/sessions/${SESSION_ID}/artifacts" \
  -H "Authorization: Bearer ${HF_OAUTH_TOKEN}" \
  -H "X-Workspace-ID: ${WORKSPACE_ID}" >"$artifacts_result"

python - "$result" "$job_result" "$artifacts_result" <<'PY'
import json
from pathlib import Path
import sys

result = json.loads(Path(sys.argv[1]).read_text())
result["job"] = json.loads(Path(sys.argv[2]).read_text())
result["artifacts"] = json.loads(Path(sys.argv[3]).read_text())["items"]
assert len(result["personas"]) == 5, result
assert result["job"]["status"] == "succeeded", result["job"]
kinds = {artifact["kind"] for artifact in result["artifacts"]}
assert {"persona.profile", "ux.report", "ux.presentation", "journey.log"} <= kinds, kinds
print(result["session"]["session_id"])
print("Validated artifact kinds:", ", ".join(sorted(kinds)))
PY
