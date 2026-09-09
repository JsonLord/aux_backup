# Stage 2 persona-generation audit

Date: 2026-08-26

## Result

**Stage 2 integration is implemented; pinned-package validation is pending.** This audit uses migration
Phase 2 in `spec.md` as the contract: generate personas in Python, serialize them to
Eyeson, attach them to JourneyTest, display them in live/report UI, and persist
distinct profiles.

## Complete

- The persona runtime exposes versioned generate, list, get, and patch endpoints.
- Offline generation creates complete, seed-reproducible identity, ability, and
  behavior structures without deriving functional restrictions from demographics.
- Profiles persist in SQLite for local development and PostgreSQL in production.
- Gradio Persona Studio displays and edits complete profiles through the persona HTTP
  client.
- Combined-test execution currently forwards a complete profile to the Journey worker
  `/v1/runs` contract.
- Persona endpoints enforce the same verified workspace/service identity boundary as
  the control plane, and both SQLite and PostgreSQL repositories scope reads and edits
  by workspace.
- Every selected persona is saved as an immutable `persona.profile` artifact before
  queueing. Jobs carry artifact IDs, and the executor resolves those exact snapshots.
- Journey worker results, persisted UX reports, orchestrator output, and Live
  Monitoring include the complete snapshot used for execution.
- Contract tests prove two distinct snapshots reach the worker and remain unchanged in
  the final persisted report.

## Required before Stage 2 can close

- `PLACEHOLDER`: execute TinyTroupe v0.7.0 from the pinned commit in a network-enabled
  Python 3.12 environment with configured model credentials. The adapter no longer
  reads `TinyPerson._persona`; it requires a supported public serialization method and
  passes `seed` when the pinned factory API declares that parameter.
- `PLACEHOLDER`: run the committed `RUN_TINY_TROUPE_ACCEPTANCE=1` package test and
  record the supported serialization method and determinism result.

## Helmholtz OpenAI-compatible configuration

The Space's historical `config.ini` selected `API_TYPE=helmholtz-blablador`, but
TinyTroupe 0.7 does not register that client name. The persona adapter now uses
the public `config_manager` and `tinytroupe.clients.force_api_type` APIs to select
the registered `openai` client, set the configured model, and route the OpenAI SDK
through `OPENAI_BASE_URL`. This ports the relevant behavior reviewed from
`JsonLord/TinyTroupe:fix-openai-auth-error` without downgrading the pinned runtime
from 0.7.0 to the fork branch's declared 0.5.2.

The deployed Space check on 2026-08-27 confirmed `api_type = openai`,
`base_url = https://api.helmholtz-blablador.fz-juelich.de/v1`, and model
`alias-large`. TinyTroupe then issued a request to that endpoint; the prior
"API type helmholtz-blablador is not supported" failure did not recur. The
provider returned HTTP 502 during this acceptance attempt, so distinct-persona
package acceptance remains pending a healthy upstream response.

## Exit check

The immutable snapshot, tenancy, worker attachment, and report requirements now have
local contract coverage. Stage 2 closes when the committed pinned-TinyTroupe test also
passes and produces multiple distinct profiles. The offline fallback remains available
but cannot satisfy that package acceptance test.
