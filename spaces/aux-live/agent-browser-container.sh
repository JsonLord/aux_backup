#!/usr/bin/env bash
set -euo pipefail

# Hugging Face Docker Spaces do not expose a Chrome user-namespace sandbox.
# Keep the container-specific browser flag at the deployment boundary rather
# than weakening browser defaults in the reusable Journey worker.
exec /home/user/app/services/journey-worker/node/node_modules/.bin/agent-browser \
  --args "--no-sandbox" "$@"
