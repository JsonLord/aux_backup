# Synthetic UX Testing Platform — Integration & Development Specification

**Document:** `spec.md`  
**Status:** Proposed implementation specification  
**Primary product base:** `JsonLord/aux_backup` → recommended new canonical product repository `JsonLord/aux`  
**Primary purpose:** Combine synthetic persona generation, stateful user-journey execution, visual UX diagnosis, pain-point attribution, grounded recommendations, alternative solution generation, and report/UI presentation into an inspectable job pipeline.

---

## 1. Goal

Build a modular synthetic UX testing platform in which:

1. **TinyTroupe generates synthetic people/personas in isolated batch jobs.**
2. A **persona/behavior compilation job** converts each rich persona into structured, machine-usable behavioral parameters, ability constraints, and task-specific policy.
3. **DSPy is used for semantic/learnable transformations** where optimization against human data is valuable.
4. **Native deterministic code is used for state transitions and physical/behavioral mechanics** such as waiting tolerance, frustration accumulation, seeded coping choices, visual transforms, pointer error, reading delays, and stop conditions.
5. **JourneyTest runs the live browser journey**, owns browser actions, video, snapshots, screenshots, DOM/accessibility evidence, and action/UI-change timelines.
6. Every JourneyTest screenshot and relevant browser state is published as evidence and can simultaneously feed **Eyeson**.
7. **Eyeson diagnoses visual/interaction UX pain**, attributes pain to concrete interface elements, creates frustration/confusion/effort visualizations, and generates structured alternative solutions.
8. A future **UX Knowledge Grounder (RAG)** can retrieve external/internal UX knowledge and ground Eyeson diagnoses and alternatives.
9. A **report enrichment job** combines JourneyTest, behavior, Eyeson, and grounding results into a product-level report.
10. A **Gradio UI** preserves and enhances the existing `aux_backup` tab register while becoming a client of the job APIs rather than the owner of business logic.
11. Every stage can be:
    - invoked independently;
    - inspected independently;
    - replayed from stored inputs;
    - used as input to a later stage;
    - composed into predefined or custom job packages.

The system MUST expose versioned FastAPI contracts so that every intermediate stage is interceptable.

---

## 2. Non-goals

The first implementation MUST NOT:

- replace JourneyTest with a second DSPy/ReAct browser agent;
- make TinyTroupe directly responsible for raw browser control;
- make screenshots the only browser observation channel;
- infer disabilities or impairments solely from age or demographic fields;
- use the LLM to update deterministic frustration/timing mathematics on every step;
- use GitHub branches as the primary job queue or database;
- require the RAG subsystem to exist before the rest of the product can run;
- require a full redesign of the current Gradio tab navigation;
- depend on `JsonLord/AI-UX` for the live browser testing runtime.

---

## 3. Architecture decision summary

### 3.1 Control plane vs execution plane

Use two primary language/runtime families.

| Layer | Language/runtime | Reason |
|---|---|---|
| API orchestration | Python 3.12 | FastAPI, Pydantic, ecosystem fit |
| Gradio UI | Python 3.12 | Existing `aux_backup` is Gradio/Python |
| Persona generation | Python 3.12 | TinyTroupe is Python |
| DSPy semantic layer | Python 3.12 | DSPy is Python; later optimization/evaluation |
| RAG/knowledge grounding | Python 3.12 | retrieval/indexing ecosystem |
| Report aggregation | Python 3.12 | structured data/report generation |
| Browser journey runtime | Node.js 24+, TypeScript | JourneyTest requires Node >=24 and is TypeScript |
| Live behavior controller | TypeScript in Journey worker | must operate synchronously around browser actions |
| Eyeson image/visual engine | Node.js 24+, TypeScript target | reuse Sharp/image code; align with Journey execution runtime |
| Thin worker API wrappers | Python 3.12/FastAPI | every service boundary remains inspectable through FastAPI |

### 3.2 DSPy vs native implementation

DSPy MUST be used selectively.

**Use DSPy for:**

- TinyPersona → structured behavioral prior compilation;
- ambiguous experience appraisal;
- persona-sensitive visual interpretation;
- UX issue interpretation/classification;
- pain-point semantic diagnosis;
- grounded solution generation;
- later optimization against labeled human UX data.

**Use native code for:**

- job orchestration;
- browser actions;
- timers and waits;
- frustration/trust/confusion state mathematics;
- repetition escalation;
- seeded probabilistic coping selection;
- state recovery/decay;
- visual impairment transforms;
- pointer imprecision and movement timing;
- reading delays;
- working-memory simulation rules;
- step limits;
- cancellation;
- evidence/artifact persistence;
- API contracts.

A `SemanticEngine` interface MUST allow both:

- `DSPySemanticEngine`
- `DirectLLMSemanticEngine`

This gives the project a baseline implementation, debugging fallback, and an A/B path for proving whether DSPy improves behavior before making it mandatory everywhere.

---

## 4. Repository disposition

### 4.1 `JsonLord/aux_backup`

**Disposition: MERGE/EVOLVE into the canonical product repository.**

Recommended canonical target:

`JsonLord/aux`

If the repository name is not changed, the same folder layout applies to `aux_backup`.

This repository becomes the product monorepo containing:

- FastAPI control plane;
- Gradio UI;
- shared contracts;
- Python persona/DSPy/RAG/report services;
- FastAPI adapters for TypeScript workers;
- imported Eyeson engine;
- integration/e2e tests;
- Docker Compose deployment definitions.

The existing large `app.py` MUST be decomposed. Gradio callbacks MUST call application services through APIs rather than contain core business logic.

### 4.2 `JsonLord/eyeson`

**Disposition: MERGE owned engine code into the product monorepo.**

Recommended destination:

`services/eyeson-engine/`

The original repository may remain archived/read-only for provenance.

Preserve useful parts:

- Sharp-based image analysis;
- visual design metrics;
- screenshot processing;
- AI critique concepts;
- report/recommendation structures.

Remove or deprecate from the main flow:

- Eyeson opening a separate browser just to recapture a URL;
- separate navigation state from JourneyTest;
- screenshot-wide critique without element IDs where element evidence is available.

All new/modified Eyeson engine code SHOULD be TypeScript. Existing JavaScript may remain during migration but touched modules SHOULD be converted.

### 4.3 `Jules-Astier/journeytest-core`

**Disposition: DO NOT physically merge into the product monorepo.**

Use as a pinned npm dependency inside an isolated Journey worker.

Current package family:

`@baguette-studios/journeytest-core`

Because behavioral hooks may require changes not currently exposed publicly, create a small maintained fork only if needed:

`JsonLord/journeytest-core`

The fork SHOULD contain generic extension points only:

- pre-action middleware;
- post-action/observation middleware;
- behavior event recorder hooks;
- screenshot/evidence publisher hooks;
- optional synchronous perception callback.

Avoid product-specific report/UI code in the fork.

Any generally useful hook SHOULD be designed so it could be contributed upstream.

### 4.4 `microsoft/TinyTroupe` / `JsonLord/TinyTroupe`

**Disposition: DO NOT merge source into the monorepo.**

Use a pinned Python dependency.

If custom patches are required, use the existing `JsonLord/TinyTroupe` fork and commit those changes into that fork.

The product MUST NOT patch installed TinyTroupe source dynamically at container startup.

Pin to an exact commit/tag through `pyproject.toml`/`uv.lock`.

### 4.5 `JsonLord/AI-UX`

**Disposition: DO NOT use as a runtime dependency.**

Reason:

Its useful concepts are prototype/journey visualization and generated visual alternatives, but it does not provide the live observe → act → observe browser cycle required by the target system.

It MAY remain a reference source for future:

- prototype rendering;
- solution visualization;
- Figma integration.

### 4.6 `JsonLord/tiny_web`

**Disposition: DEPRECATE as runtime orchestration/database.**

The existing app may continue to export reports/results to a GitHub branch for collaboration, but GitHub branches MUST NOT remain the system-of-record for job state.

Replace branch polling with API/job state.

Add an optional:

`github.export`

job that exports selected artifacts to a branch/PR when desired.

### 4.7 `JsonLord/agent-notes`

**Disposition: OPTIONAL data source only.**

If `PersonaPool` remains useful, expose it through a persona-library adapter.

Do not use this repository for cross-service IPC.

---

## 5. Target monorepo layout

```text
aux/
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── routers/
│   │   ├── dependencies/
│   │   └── settings.py
│   │
│   └── gradio/
│       ├── app.py
│       ├── tabs/
│       │   ├── orchestrator.py
│       │   ├── presentation.py
│       │   ├── reports.py
│       │   ├── persona_trace.py
│       │   ├── pain_maps.py
│       │   ├── developer_handoff.py
│       │   ├── full_ui.py
│       │   ├── system.py
│       │   ├── monitoring.py
│       │   └── styling.py
│       └── api_client.py
│
├── services/
│   ├── persona-service/
│   │   ├── api/
│   │   ├── tinytroupe_adapter/
│   │   ├── models/
│   │   └── worker/
│   │
│   ├── semantic-service/
│   │   ├── api/
│   │   ├── dspy_modules/
│   │   ├── direct_llm/
│   │   ├── evals/
│   │   └── worker/
│   │
│   ├── journey-worker/
│   │   ├── api/                  # Python FastAPI wrapper
│   │   ├── node/                 # Node 24 / TypeScript runtime
│   │   │   ├── src/
│   │   │   ├── package.json
│   │   │   └── tsconfig.json
│   │   └── worker/
│   │
│   ├── eyeson-worker/
│   │   ├── api/                  # Python FastAPI wrapper
│   │   ├── engine/               # imported/migrated Eyeson TS engine
│   │   ├── pain_resolver/
│   │   └── worker/
│   │
│   ├── knowledge-service/
│   │   ├── api/
│   │   ├── providers/
│   │   │   ├── null.py
│   │   │   ├── local_fixture.py
│   │   │   └── future_vector.py
│   │   └── models/
│   │
│   └── report-service/
│       ├── api/
│       ├── aggregate/
│       ├── renderers/
│       └── worker/
│
├── packages/
│   ├── contracts/
│   │   ├── python/
│   │   ├── openapi/
│   │   └── generated-ts/
│   │
│   ├── job-client/
│   ├── artifact-client/
│   └── ux-taxonomies/
│
├── infrastructure/
│   ├── docker/
│   ├── compose/
│   ├── migrations/
│   └── observability/
│
├── fixtures/
│   ├── ux-lab/
│   ├── personas/
│   ├── screenshots/
│   └── knowledge/
│
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   └── load/
│
├── pyproject.toml
├── uv.lock
├── docker-compose.yml
└── spec.md
```

---

## 6. Communication rule

### 6.1 Mandatory rule

No service may import another service's application implementation directly.

Cross-service communication MUST happen via:

1. versioned FastAPI endpoints;
2. artifact references;
3. job IDs;
4. versioned JSON/Pydantic contracts.

A queue such as Redis/Celery MAY transport job IDs internally, but domain payloads MUST be persisted and retrievable through the APIs.

### 6.2 Why

This enables:

- intercepting any stage;
- replaying a stage from an existing artifact;
- replacing a stage;
- using one stage alone;
- debugging failed pipelines;
- external clients calling individual services;
- custom pipeline packages.

---

## 7. Persistence and job infrastructure

### 7.1 System of record

Use PostgreSQL for:

- sessions;
- jobs;
- job dependencies;
- job attempts;
- job events;
- artifact metadata;
- pipeline definitions;
- pipeline runs.

For local development, SQLite MAY be temporarily supported, but CI and integration tests SHOULD include PostgreSQL.

### 7.2 Artifact storage

Development:

`./data/artifacts/`

Production-ready abstraction:

S3-compatible object storage.

Artifact examples:

- TinyTroupe persona JSON;
- normalized persona JSON;
- behavior profile JSON;
- journey definition;
- JourneyTest `run.json`;
- JourneyTest raw `report.md`;
- `dashboard.html`;
- `video.webm`;
- screenshots;
- accessibility snapshots;
- DOM snapshots;
- UI-change JSON;
- behavior event NDJSON;
- perceived screenshots;
- Eyeson findings;
- pain-point JSON;
- knowledge references;
- alternatives;
- enriched report;
- slide decks;
- generated UI assets.

### 7.3 Queue

Heavy jobs MUST NOT rely only on FastAPI `BackgroundTasks`.

Recommended production target:

- Redis;
- Celery workers or equivalent durable queue;
- one named queue per execution class.

Example queues:

```text
persona
semantic
journey
eyeson
knowledge
report
generation
export
```

The queue message SHOULD contain only:

```json
{
  "job_id": "job_...",
  "attempt": 1
}
```

The worker obtains the job specification and artifacts through the API/storage layer.

---

## 8. Core identifiers

Every object MUST be traceable.

Required identifiers:

- `session_id`
- `pipeline_run_id`
- `job_id`
- `attempt_id`
- `persona_id`
- `synthetic_user_id`
- `journey_run_id`
- `step_id`
- `screen_id`
- `artifact_id`
- `pain_point_id`
- `alternative_id`

Never use a GitHub branch name as the only identifier.

A session MAY have:

`external_ref.github_branch`

for export compatibility.

---

## 9. Job model

### 9.1 Job statuses

```text
queued
running
waiting_on_dependency
succeeded
failed
cancel_requested
cancelled
```

### 9.2 Base job record

```json
{
  "job_id": "job_01...",
  "session_id": "ses_01...",
  "pipeline_run_id": "pipe_01...",
  "type": "persona.generate.batch",
  "version": "1.0",
  "status": "queued",
  "depends_on": [],
  "input_artifacts": [],
  "output_artifacts": [],
  "created_at": "...",
  "started_at": null,
  "ended_at": null,
  "attempt": 1,
  "seed": 42,
  "metadata": {}
}
```

### 9.3 Job events

Each meaningful transition MUST emit an event.

```json
{
  "sequence": 17,
  "job_id": "job_01...",
  "type": "journey.screenshot.created",
  "timestamp": "...",
  "progress": 0.43,
  "data": {
    "step_id": "step_012",
    "artifact_id": "art_012"
  }
}
```

Events MUST be persisted before being streamed.

---

## 10. Canonical FastAPI control-plane endpoints

Mount the Gradio application at:

`/ui`

Reserve the standard FastAPI endpoints:

- `/docs`
- `/redoc`
- `/openapi.json`

### 10.1 Health

```text
GET /healthz
GET /readyz
GET /v1/system/services
```

### 10.2 Sessions

```text
POST /v1/sessions
GET  /v1/sessions/{session_id}
GET  /v1/sessions/{session_id}/jobs
GET  /v1/sessions/{session_id}/artifacts
GET  /v1/sessions/{session_id}/report
DELETE /v1/sessions/{session_id}
```

### 10.3 Jobs

```text
POST /v1/jobs
GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/cancel
POST /v1/jobs/{job_id}/retry
GET  /v1/jobs/{job_id}/events
GET  /v1/jobs/{job_id}/events/stream
GET  /v1/jobs/{job_id}/result
```

`events/stream` SHOULD use Server-Sent Events.

### 10.4 Artifacts

```text
POST /v1/artifacts
GET  /v1/artifacts/{artifact_id}
GET  /v1/artifacts/{artifact_id}/content
GET  /v1/artifacts/{artifact_id}/metadata
```

### 10.5 Pipeline packages

```text
GET  /v1/pipeline-packages
POST /v1/pipeline-packages
GET  /v1/pipeline-packages/{package_id}
POST /v1/pipeline-packages/{package_id}/run
POST /v1/pipelines/run
GET  /v1/pipelines/{pipeline_run_id}
POST /v1/pipelines/{pipeline_run_id}/cancel
```

---

## 11. Stage-specific FastAPI endpoints

Each stage MUST also have a direct endpoint.

These are available through the control plane even if implemented by separate workers.

### 11.1 Persona generation

```text
POST /v1/personas/generate
POST /v1/personas/generate-batch
GET  /v1/personas/{persona_id}
GET  /v1/persona-batches/{batch_id}
```

Input example:

```json
{
  "count": 20,
  "theme": "international university applications",
  "customer_profile": "prospective international students",
  "scenario": "mobile use while commuting",
  "seed": 123,
  "generator": "tinytroupe",
  "additional_constraints": []
}
```

### 11.2 Persona normalization/behavior compilation

```text
POST /v1/behavior-profiles/compile
POST /v1/behavior-profiles/compile-batch
GET  /v1/behavior-profiles/{profile_id}
```

Inputs:

- TinyTroupe persona artifact;
- explicit functional abilities;
- scenario;
- task;
- semantic engine (`dspy` or `direct`).

### 11.3 Journey execution

```text
POST /v1/journeys/run
GET  /v1/journeys/runs/{journey_run_id}
POST /v1/journeys/runs/{journey_run_id}/cancel
GET  /v1/journeys/runs/{journey_run_id}/events/stream
```

### 11.4 Eyeson analysis

```text
POST /v1/eyeson/screens/analyze
POST /v1/eyeson/runs/analyze
POST /v1/eyeson/pain-points/resolve
GET  /v1/eyeson/pain-points/{pain_point_id}
```

### 11.5 Alternatives

```text
POST /v1/alternatives/generate
POST /v1/alternatives/{alternative_id}/visualize
GET  /v1/alternatives/{alternative_id}
```

### 11.6 Knowledge grounding

```text
POST /v1/knowledge/search
GET  /v1/knowledge/providers
POST /v1/knowledge/index
```

The first implementation MUST include a `null` provider.

### 11.7 Reports

```text
POST /v1/reports/build
GET  /v1/reports/{report_id}
GET  /v1/reports/{report_id}/markdown
GET  /v1/reports/{report_id}/html
```

---

## 12. Gradio API endpoints

FastAPI is the canonical machine API.

Gradio API endpoints are convenience endpoints for users already consuming the Gradio application with `gradio_client`.

Every important Gradio action MUST have an explicit `api_name`.

Recommended Gradio API names:

```text
/generate_persona_batch
/compile_behavior_profiles
/run_journey_only
/run_ux_only
/run_combined_test
/run_full_solution_pipeline
/run_custom_pipeline
/get_pipeline_status
/cancel_pipeline
/get_report
/get_pain_map
/generate_alternatives
/generate_full_ui
/export_to_github
```

A custom pipeline can also be registered with `gr.api(...)` if it does not map naturally to a visible button.

Gradio callbacks MUST call the FastAPI client. They MUST NOT duplicate job logic.

---

## 13. Predefined job packages

### 13.1 `persona_only`

```text
persona.generate.batch
→ persona.normalize
→ behavior.compile
```

### 13.2 `journey_only`

Inputs:

- pre-existing behavior profile;
- task;
- URL.

```text
journey.run
→ report.build(raw)
```

### 13.3 `ux_only`

Inputs:

- screenshot(s);
- element map;
- optional behavior evidence.

```text
eyeson.screen.analyze
→ pain.resolve
→ knowledge.search(optional)
→ alternatives.generate(optional)
→ report.build
```

### 13.4 `combined_test`

```text
persona.generate.batch
→ behavior.compile
→ journey.run
   ├─ screenshots → eyeson.screen.analyze (fan-out)
   ├─ behavior events
   └─ final JourneyTest artifacts
→ pain.resolve
→ knowledge.search
→ alternatives.generate
→ report.build
```

### 13.5 `full_solution_pipeline`

```text
combined_test
→ alternatives.visualize
→ optional generated UI
→ optional rerun alternative
→ comparison report
→ presentation generation
```

---

## 14. Custom pipeline definition

A custom package is a DAG.

Example:

```json
{
  "name": "three-persona-journey-with-ux",
  "version": "1.0",
  "inputs": {
    "url": "https://example.com",
    "task": "Complete checkout"
  },
  "steps": [
    {
      "id": "personas",
      "type": "persona.generate.batch",
      "config": {"count": 3}
    },
    {
      "id": "behavior",
      "type": "behavior.compile",
      "depends_on": ["personas"],
      "map_over": "personas.outputs.personas"
    },
    {
      "id": "journey",
      "type": "journey.run",
      "depends_on": ["behavior"],
      "map_over": "behavior.outputs.profiles"
    },
    {
      "id": "eyeson",
      "type": "eyeson.run.analyze",
      "depends_on": ["journey"],
      "map_over": "journey.outputs.runs"
    },
    {
      "id": "report",
      "type": "report.build",
      "depends_on": ["journey", "eyeson"]
    }
  ]
}
```

Validation MUST reject:

- cycles;
- missing dependencies;
- unknown job types;
- incompatible artifact types;
- missing required inputs.

---

## 15. Artifact contracts

### 15.1 Persona artifact

```json
{
  "schema_version": "1.0",
  "persona_id": "per_...",
  "generator": {
    "name": "tinytroupe",
    "version": "...",
    "commit": "..."
  },
  "seed": 42,
  "persona": {},
  "provenance": {}
}
```

### 15.2 Behavior profile artifact

```json
{
  "schema_version": "1.0",
  "profile_id": "beh_...",
  "persona_id": "per_...",
  "traits": {
    "patience": 0.4,
    "persistence": 0.8,
    "irritability": 0.6,
    "anger_reactivity": 0.7,
    "anger_recovery": 0.3,
    "impulsivity": 0.2,
    "failure_tolerance": 0.5,
    "repeat_failure_tolerance": 0.3,
    "ambiguity_tolerance": 0.4,
    "help_seeking": 0.5,
    "exploration": 0.4,
    "risk_tolerance": 0.3,
    "self_efficacy": 0.7,
    "digital_confidence": 0.6,
    "verification_tendency": 0.8
  },
  "abilities": {
    "vision": {},
    "motor": {},
    "cognition": {}
  },
  "context": {},
  "semantic_engine": "dspy",
  "compiler_version": "1.0",
  "seed": 42
}
```

### 15.3 Ability rule

Age/demographic information MUST NOT automatically produce an impairment.

If an ability value is unspecified:

- leave it typical/default;
- or sample from an explicitly selected population model;
- record the model used.

### 15.4 Journey runtime profile

```json
{
  "schema_version": "1.0",
  "synthetic_user_id": "usr_...",
  "persona_artifact_id": "art_...",
  "behavior_profile_artifact_id": "art_...",
  "task": {},
  "scenario": {},
  "seed": 42
}
```

### 15.5 User state

```json
{
  "frustration": 0.0,
  "anger": 0.0,
  "confusion": 0.0,
  "trust": 0.7,
  "confidence": 0.7,
  "cognitive_effort": 0.0,
  "physical_effort": 0.0,
  "fatigue": 0.0,
  "perceived_progress": 0.0,
  "consecutive_failures": 0,
  "coping_mode": "normal"
}
```

### 15.6 Experience event

```json
{
  "event_id": "evt_...",
  "type": "software_failure",
  "severity": 0.7,
  "duration_ms": 6400,
  "goal_blocked": true,
  "progress_visible": false,
  "repeat_key": "checkout-submit",
  "attribution": {
    "software": 0.6,
    "interface": 0.3,
    "capability": 0.0,
    "user": 0.1
  },
  "recovery_quality": 0.2,
  "evidence": []
}
```

### 15.7 Coping decision

```json
{
  "decision": "impulsive_retry",
  "probabilities": {
    "retry": 0.22,
    "reread": 0.06,
    "wait": 0.03,
    "explore": 0.07,
    "seek_help": 0.09,
    "impulsive_retry": 0.42,
    "abandon": 0.11
  },
  "seed": 42,
  "sample_index": 11
}
```

### 15.8 Screen evidence

```json
{
  "screen_id": "screen_...",
  "journey_run_id": "jr_...",
  "step_id": "step_012",
  "timestamp_ms": 48730,
  "url": "https://example.com/checkout",
  "screenshot_artifact_id": "art_...",
  "snapshot_artifact_id": "art_...",
  "ui_change_artifact_id": "art_...",
  "elements": [
    {
      "id": "@e17",
      "role": "button",
      "label": "Continue",
      "box": {
        "x": 315,
        "y": 532,
        "width": 132,
        "height": 44
      }
    }
  ]
}
```

### 15.9 Pain point

```json
{
  "pain_point_id": "pain_...",
  "title": "Insufficient feedback after Continue",
  "severity": "high",
  "steps": ["step_012", "step_013"],
  "behavioral_impact": {
    "frustration_delta": 0.31,
    "confusion_delta": 0.22,
    "trust_delta": -0.14,
    "retries": 2,
    "backtracks": 0,
    "elapsed_cost_ms": 11300
  },
  "elements": [
    {
      "element_id": "@e17",
      "role": "trigger",
      "contribution": 0.6,
      "confidence": 0.9
    }
  ],
  "diagnosis": {},
  "grounding": {},
  "alternatives": []
}
```

### 15.10 Alternative

```json
{
  "alternative_id": "alt_...",
  "pain_point_ids": ["pain_..."],
  "title": "Persistent processing state",
  "strategy": "feedback",
  "proposed_change": "Disable duplicate submission and show persistent processing feedback.",
  "rationale": "...",
  "expected_impact": {
    "frustration": "lower",
    "confusion": "lower",
    "task_success": "higher"
  },
  "effort": "low",
  "confidence": 0.82,
  "grounding_refs": [],
  "visual_artifact_id": null
}
```

---

## 16. JourneyTest integration

### 16.1 Ownership

JourneyTest MUST own:

- live browser session;
- URL navigation;
- click/fill/type/scroll/wait;
- video recording;
- screenshots;
- semantic/accessibility snapshots;
- DOM state;
- UI-change observation;
- network/console evidence;
- journey success/fail/blocker criteria;
- raw JourneyTest `run.json`.

### 16.2 Product wrapper

Do not break JourneyTest's strict upstream `RunResult` schema.

Instead create a product-level envelope:

```json
{
  "schema_version": "1.0",
  "session_id": "...",
  "synthetic_user_id": "...",
  "journeytest": {
    "run_result_artifact_id": "...",
    "dashboard_artifact_id": "...",
    "video_artifact_id": "..."
  },
  "behavior": {},
  "eyeson": {},
  "grounding": {},
  "alternatives": {},
  "report": {}
}
```

This isolates upstream changes from the product schema.

### 16.3 Behavior hooks

Behavior logic MUST be injected around JourneyTest browser actions.

Conceptual flow:

```text
before action
→ BehaviorController.beforeAction
→ physical/timing modifiers
→ JourneyTest browser action
→ JourneyTest UI-change observation
→ native experience classifier
→ DSPy appraisal only if ambiguous
→ StateReducer
→ CopingPolicy
→ next agent observation/action
```

### 16.4 Synchronous vs asynchronous analysis

Synchronous:

- information required for the next user decision;
- persona perception when visual limitations change what the user can see;
- state/coping calculation.

Asynchronous:

- deep Eyeson critique;
- report prose;
- knowledge grounding;
- alternative generation;
- presentation generation.

---

## 17. Behavior controller

The live behavior controller SHOULD live in the Journey worker's TypeScript process.

Reason:

- no network round trip for every state update;
- deterministic behavior;
- low latency;
- direct access to action/result metadata;
- seed reproducibility.

Required modules:

```text
behavior/
├── state.ts
├── stateReducer.ts
├── waitingTolerance.ts
├── failureModel.ts
├── copingPolicy.ts
├── seededRandom.ts
├── motorModel.ts
├── readingModel.ts
├── perceptionPolicy.ts
└── events.ts
```

DSPy MAY be called through FastAPI only for ambiguous semantic appraisal.

---

## 18. Persona and DSPy jobs

### 18.1 Job A — persona generation

`persona.generate.batch`

Input:

- target population description;
- theme;
- scenario;
- count;
- seed.

Output:

- one persona artifact per person;
- one batch manifest.

This job MUST be reusable without starting a browser.

### 18.2 Job B — persona normalization

`persona.normalize`

Purpose:

Convert TinyTroupe-specific JSON into the product's stable persona contract.

Do not discard the original persona artifact.

### 18.3 Job C — behavior compilation

`behavior.compile`

Input:

- normalized persona;
- explicit functional ability profile;
- scenario;
- task.

Output:

- behavior profile;
- provenance;
- semantic engine used.

DSPy is appropriate here because this mapping can later be optimized against observed human behavior.

### 18.4 Job D — agent runtime assembly

`agent-runtime.prepare`

Input:

- behavior profile;
- task;
- scenario;
- browser/device context.

Output:

- Journey runtime profile;
- initial UserState;
- explicit physical/perception constraints.

---

## 19. Eyeson integration

### 19.1 Eyeson MUST be an evidence consumer

Eyeson MUST NOT open a second browser session during a combined run.

JourneyTest is the source of canonical screenshots and state.

When JourneyTest emits:

`journey.screenshot.created`

the orchestrator SHOULD enqueue or fan out:

`eyeson.screen.analyze`

### 19.2 Eyeson responsibilities

Eyeson SHOULD provide:

- screenshot visual analysis;
- element-region analysis;
- before/after crop comparison;
- visual hierarchy/saliency;
- typography/spacing/color metrics;
- pain-point candidate ranking;
- frustration/confusion/effort overlays;
- root-cause diagnosis;
- alternative generation input;
- optional persona-view visual analysis.

### 19.3 Element mapping

Every screenshot intended for element-level UX reasoning SHOULD include:

- stable semantic element ID;
- role;
- accessible label;
- bounding box;
- visibility;
- current state;
- relation to clicked/changed element.

The screenshot, semantic snapshot, and element map MUST refer to the same browser state.

---

## 20. Pain and frustration visualization

The UI/report MUST distinguish:

- frustration;
- confusion;
- missed/overlooked controls;
- repeated actions;
- cognitive effort;
- physical effort;
- trust drop.

Do not collapse all metrics into one heatmap.

Element friction score MAY begin as:

```text
behavioral_delta
× attribution_confidence
× element_contribution
```

The UI MUST label model-derived scores as estimates until empirically calibrated.

---

## 21. RAG/UX knowledge roadmap placeholder

### 21.1 Interface

Create immediately:

```python
class UXKnowledgeProvider(Protocol):
    async def search(self, query: UXKnowledgeQuery) -> list[UXKnowledgeResult]:
        ...
```

### 21.2 Providers

Initial:

- `NullUXKnowledgeProvider`
- `FixtureUXKnowledgeProvider`

Roadmap:

- WCAG/WAI corpus;
- Nielsen heuristic corpus;
- GOV.UK/design-system patterns;
- Material/HIG/platform guidance where licensing/usage permits;
- published UX research;
- internal design system;
- internal user-research reports;
- support tickets;
- experiment/A-B results.

### 21.3 Rule

Diagnosis first, retrieval second.

Correct:

```text
observed behavioral pain
+ visual evidence
→ diagnosis
→ retrieve relevant knowledge
→ ground/refine recommendation
```

Avoid:

```text
retrieve heuristic
→ search UI for something that violates it
```

### 21.4 Grounding status

Every finding/alternative MUST expose:

```text
not_configured
pending
grounded
failed
```

Never represent an ungrounded model recommendation as grounded.

---

## 22. Report architecture

### 22.1 Keep raw JourneyTest report

Preserve raw:

- `run.json`
- `report.md`
- `dashboard.html`

as source artifacts.

### 22.2 Add product-level enriched report

Create a separate report job.

The enriched report MUST include:

1. Executive summary
2. Synthetic user
3. Behavioral/ability profile
4. Journey outcome
5. Experience trajectory
6. Critical pain episodes
7. Element-level UX diagnosis
8. Eyeson visual review
9. Alternatives
10. Grounding/knowledge basis
11. Full evidence timeline
12. Raw JourneyTest artifact links

### 22.3 Evidence vs inference

Every report item SHOULD visually separate:

**Observed**

- browser action;
- waiting time;
- DOM/UI changes;
- screenshots;
- retries;
- behavior state delta.

**Inferred**

- likely root cause;
- persona interaction;
- attribution confidence.

**Grounded**

- external/internal knowledge references.

**Proposed**

- alternative solution;
- expected impact;
- effort/confidence.

---

## 23. Gradio UI plan

The existing tab register is retained and enhanced.

### 23.1 Analysis Orchestrator

Keep tab name.

Enhance with:

- URL;
- task;
- scenario;
- persona generation method;
- number of personas;
- iterations per persona;
- seed/randomness;
- device/viewport;
- testing mode:
  - Journey only
  - UX feedback only
  - Combined
  - Full solution
  - Custom pipeline
- semantic engine:
  - Direct
  - DSPy
- ability profile:
  - Typical/default
  - Explicit preset
  - Advanced manual
- RAG grounding:
  - Off
  - Fixture
  - Configured provider
- pipeline DAG preview;
- Start button;
- Cancel button;
- live stage status.

Replace GitHub-branch session orchestration with `session_id`.

Optional field:

`Export branch name`.

### 23.2 Presentation Carousel

Keep.

Source presentation decks from report artifacts rather than only polling GitHub.

Add:

- run selector;
- report version;
- original vs alternative comparison decks.

### 23.3 Report Viewer

Keep.

Add top-level mode switch:

```text
User Journey | UX Feedback | Root Causes | Solutions | Knowledge
```

Persist:

- selected synthetic user;
- selected step;
- video timestamp;
- selected screen

when switching modes.

#### User Journey

Show:

- video;
- current screenshot;
- timeline;
- frustration/confusion/trust/fatigue graphs;
- current coping decision;
- behavioral state transitions;
- raw evidence links.

#### UX Feedback

Show:

- screenshot;
- element overlays;
- Eyeson findings;
- severity;
- affected behavior;
- linked video moment.

#### Root Causes

Show:

- pain episodes;
- affected users;
- causal element graph;
- behavioral impacts;
- attribution confidence.

#### Solutions

Show:

- structured alternatives;
- impact/effort/confidence;
- generated visual variants when available;
- select solutions for downstream UI generation.

#### Knowledge

Show:

- grounding status;
- retrieved sources;
- principle/relevance;
- clear distinction between retrieved content and model inference.

### 23.4 Persona Thought Logs

Preserve tab position but rename visible heading to:

`Persona & Behavior Trace`

Do not make provider-private hidden chain-of-thought a system dependency.

Show auditable simulation outputs:

- persona identity;
- TinyTroupe explicit simulated thoughts if generated as output;
- goals;
- attention;
- emotions;
- concise decision rationale;
- UserState;
- ExperienceEvent;
- CopingDecision;
- action;
- result.

### 23.5 Average User Journey Heatmaps

Keep tab; enhance heading to:

`Cohort Pain Maps & Heatmaps`

Controls:

```text
Frustration
Confusion
Missed elements
Repeated actions
Cognitive effort
Physical effort
Eyeson issue density
```

Filters:

- persona;
- cohort;
- ability profile;
- step/screen;
- completed/abandoned;
- iteration.

### 23.6 Agents.txt

Keep.

Enhance to:

`Developer Handoff (Agents.txt)`

Output:

- selected pain points;
- grounded recommendations;
- selected alternatives;
- evidence refs;
- implementation acceptance criteria;
- coding-agent prompt;
- downloadable JSON/Markdown.

### 23.7 Full New UI

Keep.

Enhance with:

- original screenshot/site;
- selected alternatives;
- generated alternative;
- side-by-side comparison;
- "Rerun selected synthetic users" action;
- before/after scorecard;
- design chat.

### 23.8 System

Keep.

Show:

- service health;
- worker queue health;
- versions/commits:
  - TinyTroupe
  - JourneyTest
  - Eyeson
  - DSPy
- model providers;
- FastAPI OpenAPI links;
- Gradio API link;
- storage status;
- database status;
- artifact retention;
- GitHub export configuration.

### 23.9 Live Monitoring

Keep.

Replace branch polling as primary behavior with:

- pipeline DAG;
- job status cards;
- SSE event stream;
- current running persona;
- current JourneyTest step;
- screenshot thumbnails;
- Eyeson queue depth;
- cancellation/retry controls.

GitHub export monitoring MAY remain a secondary panel.

### 23.10 Alternative Styling

Keep.

Use for:

- visual solution styles;
- generated alternative variants;
- future Figma/onlook integration;
- design-system selection;
- visual generation settings.

---

## 24. Gradio code structure

Do not keep all tabs in one `app.py`.

Each tab MUST be a function/module.

Example:

```python
def build_report_tab(client: OrchestratorClient, state: AppState):
    ...
```

Shared UI state SHOULD contain IDs, not large business objects.

Example:

```python
@dataclass
class AppState:
    session_id: str | None
    pipeline_run_id: str | None
    synthetic_user_id: str | None
    step_id: str | None
    report_id: str | None
```

---

## 25. Current Gradio/FastAPI migration rules

The current application mounts Gradio into FastAPI. Keep that architecture, but:

- mount Gradio at `/ui`;
- keep `/docs` for FastAPI OpenAPI;
- remove the handwritten `/api-docs` JSON endpoint;
- explicitly name Gradio APIs with `api_name`;
- remove runtime monkey-patching of Gradio site-packages;
- pin a tested Gradio version in `uv.lock`;
- upgrade Gradio only after UI/API smoke tests pass.

---

## 26. Type contracts

Canonical external contracts SHOULD be Pydantic models in the Python control plane.

Generate OpenAPI.

TypeScript worker clients SHOULD be generated from OpenAPI or checked against exported JSON Schema.

Do not manually maintain divergent Python and TypeScript definitions without contract tests.

Every artifact schema MUST include:

- `schema_version`;
- producer name;
- producer version;
- created timestamp;
- provenance/input artifact references.

---

## 27. Observability

### 27.1 Application traces

Record:

```text
session
→ pipeline
→ job
→ stage
→ LLM call
→ browser action
→ evidence
→ behavior transition
→ Eyeson finding
→ alternative
```

### 27.2 Langfuse

Add an optional Langfuse adapter.

Log:

- prompts/signatures;
- model name;
- inputs/outputs after redaction;
- explicit decision rationale;
- behavior state transitions;
- job IDs;
- artifact IDs.

Do not require hidden provider chain-of-thought.

### 27.3 Correlation

Every log line SHOULD contain:

- `session_id`
- `pipeline_run_id`
- `job_id`
- `synthetic_user_id` where applicable.

---

## 28. Security and robustness

- Treat website content as untrusted data.
- Preserve JourneyTest's origin restrictions.
- Add SSRF protections for target URLs.
- Use dedicated test accounts.
- Redact secrets from text logs.
- Treat screenshots/video as potentially containing secrets.
- Do not expose raw auth/browser-state files as artifacts.
- Use API auth before public deployment.
- Add request size limits.
- Add per-service timeout and concurrency limits.
- Cancellation MUST propagate to subprocess workers.
- Node subprocesses MUST be terminated on cancellation/timeout.
- Artifact paths MUST be sandboxed to the session/job directory.

---

# 29. Development stages and mandatory tests

No stage is complete until its acceptance tests pass.

---

## Stage 0 — Baseline and repository consolidation

### Deliverables

- create canonical product monorepo from `aux_backup`;
- import Eyeson engine under `services/eyeson-worker/engine`;
- preserve existing Gradio tab register;
- split Gradio entrypoint from business logic;
- create Docker Compose;
- add Python 3.12 control-plane image;
- add Node 24 Journey worker image;
- lock Python dependencies with `uv`;
- lock Node dependencies;
- remove runtime source patching where possible;
- add service version endpoint.

### Required tests

**Repository smoke**

```text
PASS: Python control-plane image builds.
PASS: Journey worker Node 24 image builds.
PASS: Eyeson worker image builds.
PASS: TinyTroupe imports from pinned dependency.
PASS: Gradio starts.
PASS: FastAPI /healthz returns 200.
```

**UI preservation**

Automated browser smoke MUST verify tabs exist:

```text
Analysis Orchestrator
Presentation Carousel
Report Viewer
Persona Thought Logs / Persona & Behavior Trace
Average User Journey Heatmaps
Agents.txt
Full New UI
System
Live Monitoring
Alternative Styling
```

**Regression**

Existing persona example loading MUST still work.

### Exit criterion

A developer can run:

```bash
docker compose up
```

and reach `/ui`, `/docs`, and `/healthz`.

---

## Stage 1 — Job control plane

### Deliverables

- Session model;
- Job model;
- Artifact model;
- Pipeline model;
- PostgreSQL migrations;
- Redis/queue;
- worker base class;
- SSE event stream;
- cancellation;
- retries;
- artifact service.

### Required tests

**API**

```text
PASS: POST /v1/sessions returns a session ID.
PASS: POST /v1/jobs returns HTTP 202 and job ID.
PASS: GET job transitions queued → running → succeeded.
PASS: failed job stores structured error.
PASS: retry creates a new attempt.
PASS: cancel moves a running fixture job to cancelled.
PASS: events are ordered by sequence.
PASS: SSE reconnect can resume from last event ID.
```

**Persistence**

```text
PASS: restart API while job metadata remains available.
PASS: artifact survives API restart.
```

**Idempotency**

Same idempotency key MUST NOT start duplicate expensive jobs.

### Exit criterion

A dummy 5-second worker can be queued, monitored, cancelled, retried, and inspected entirely through FastAPI.

---

## Stage 2 — TinyTroupe persona batch service

### Deliverables

- TinyTroupe adapter;
- persona generation endpoint;
- batch generation;
- normalized persona schema;
- persona library adapter;
- artifact provenance.

### Required tests

```text
PASS: request count=5 produces exactly 5 persona artifacts.
PASS: every output validates against PersonaArtifact schema.
PASS: original TinyTroupe JSON is preserved.
PASS: normalized persona has stable product schema.
PASS: generator version/commit is stored.
PASS: batch can run without JourneyTest.
PASS: one persona artifact can be fetched and reused later.
```

**Bias/ability separation**

```text
PASS: age alone does not create a non-typical vision/motor/cognition limitation.
PASS: explicitly requested limitation is preserved.
PASS: ability provenance says whether value was user-set, default, or sampled.
```

### Exit criterion

The Persona tab/API can generate reusable persona batches independently.

---

## Stage 3 — Semantic engine and DSPy parity

### Deliverables

- `SemanticEngine` protocol;
- direct structured-LLM implementation;
- DSPy implementation;
- `CompileBehaviorProfile`;
- basic DSPy evaluation dataset;
- same Pydantic output contract for both engines.

### Required tests

**Contract parity**

```text
PASS: direct engine output validates.
PASS: DSPy engine output validates.
PASS: numeric traits remain within [0,1].
PASS: required fields never disappear.
```

**Reproducibility**

Record:

- model;
- DSPy program version;
- prompt/signature version;
- seed;
- input persona artifact.

**Evaluation gate**

Create a small labeled fixture dataset.

DSPy SHOULD NOT become the default compiler until:

```text
PASS: schema validity >= direct baseline.
PASS: hallucination/unsupported-trait rate <= direct baseline.
PASS: human-reviewed persona fidelity >= agreed threshold.
```

### Exit criterion

A behavior profile can be compiled with either `semantic_engine=dspy` or `semantic_engine=direct` through the same API.

---

## Stage 4 — JourneyTest worker API

### Deliverables

- FastAPI wrapper around Node 24 JourneyTest worker;
- pinned JourneyTest package/fork;
- NDJSON progress protocol from Node subprocess to wrapper;
- artifact publishing;
- cancellation;
- raw JourneyTest report preservation.

### Required fixture application

Create `fixtures/ux-lab` with deterministic routes:

```text
/simple-success
/delayed-response
/repeated-failure
/ambiguous-save
/form-error
/small-target
/color-only-status
/prompt-injection
```

### Required tests

```text
PASS: Journey worker runs /simple-success.
PASS: raw JourneyTest verdict is passed.
PASS: run.json is stored.
PASS: video.webm is stored when video is enabled.
PASS: at least one screenshot is stored.
PASS: semantic snapshot is stored.
PASS: UI-change artifact is stored for changing action.
PASS: FastAPI request returns 202 rather than blocking until journey completion.
PASS: cancellation terminates the Node process.
```

**Security**

```text
PASS: page text in /prompt-injection cannot redefine system/tool rules.
PASS: disallowed origin navigation is blocked.
```

### Exit criterion

JourneyTest can be used independently as a backend job through FastAPI.

---

## Stage 5 — Stateful behavior and coping runtime

### Deliverables

- UserState;
- ExperienceEvent;
- StateReducer;
- waiting tolerance;
- repetition model;
- anger/frustration recovery;
- CopingPolicy;
- seeded RNG;
- JourneyTest pre/post action hooks;
- behavior event artifact.

### Required tests

**Waiting**

Given identical task/context:

```text
PASS: low-patience profile has lower effective wait tolerance than high-patience profile.
```

**Repeated failure**

```text
PASS: repeated identical failures increase repetition count.
PASS: third repeated failure produces >= first-failure frustration delta under escalation model.
```

**Anger**

```text
PASS: high anger-recovery profile decays anger faster than low-recovery profile after recovery event.
```

**Persistence**

```text
PASS: high-persistence/low-anger user does not automatically abandon after one recoverable failure.
PASS: low-persistence/high-frustration profile can select abandon.
```

**Seed**

```text
PASS: identical profile + seed + event history produces identical coping choices.
PASS: different seeds can produce different valid choices.
```

**Separation**

```text
PASS: native StateReducer can run with all LLM providers disabled.
```

### Exit criterion

A journey visibly diverges between at least two behavior profiles on the delayed/repeated-failure fixtures.

---

## Stage 6 — Eyeson screenshot evidence pipeline

### Deliverables

- Eyeson engine imported/migrated;
- Journey screenshot event → Eyeson job fan-out;
- screenshot hash/deduplication;
- element map support;
- crop generation;
- deep analysis can run asynchronously;
- optional persona perception path.

### Required tests

```text
PASS: Eyeson analyzes a JourneyTest screenshot without opening a new browser.
PASS: Eyeson result references the exact source screen_id.
PASS: duplicate screenshot hash does not create duplicate deep-analysis job unless forced.
PASS: element bounding boxes survive API serialization.
PASS: known small-target fixture identifies the target region.
PASS: deep Eyeson analysis does not block JourneyTest's next browser action.
```

**Synchronous perception**

For a color-vision fixture:

```text
PASS: transformed persona-view artifact differs from original.
PASS: original screenshot remains unchanged and available.
```

### Exit criterion

Each JourneyTest screen can be independently analyzed by Eyeson and linked back to its exact step/video moment.

---

## Stage 7 — Pain episodes, root causes, RAG placeholder, alternatives

### Deliverables

- pain-episode aggregator;
- element attribution;
- root-cause diagnosis;
- `UXKnowledgeProvider`;
- null provider;
- fixture provider;
- alternative generator;
- grounding status.

### Required tests

**Pain aggregation**

```text
PASS: four contiguous frustration events around same goal can aggregate into one pain episode.
PASS: unrelated later issue remains separate.
```

**Attribution**

```text
PASS: repeated click on known fixture button includes the clicked element as candidate.
PASS: changed error element can be attributed as feedback/cause.
PASS: contribution values are normalized/valid.
```

**RAG placeholder**

```text
PASS: Null provider returns [] and status=not_configured.
PASS: report still completes with RAG disabled.
```

**Grounded fixture provider**

```text
PASS: known form-error query returns fixture knowledge source.
PASS: grounding includes stable source ID.
PASS: model cannot mark result grounded when references=[].
```

**Alternatives**

```text
PASS: every alternative references at least one pain_point_id.
PASS: alternative includes rationale, effort, confidence and expected impact.
PASS: alternative generation can run from a stored pain-point artifact without rerunning JourneyTest.
```

### Exit criterion

A fixture journey yields an inspectable chain:

```text
behavioral pain
→ element
→ diagnosis
→ optional knowledge
→ alternative
```

---

## Stage 8 — Enriched report and output UI

### Deliverables

- product-level AnalysisRunEnvelope;
- report aggregation service;
- enriched Markdown/HTML;
- Gradio report modes;
- synchronized video/timeline;
- pain maps;
- solution selection.

### Required tests

**Report**

```text
PASS: raw JourneyTest report remains accessible.
PASS: enriched report includes persona.
PASS: enriched report includes journey outcome.
PASS: enriched report includes state trajectory.
PASS: enriched report includes pain points.
PASS: each major pain point includes evidence.
PASS: alternatives appear under their pain point.
PASS: grounding status is visible.
```

**Mode switching**

Automated UI test:

```text
1. select user X
2. select step 12
3. switch User Journey → UX Feedback
4. PASS: user X remains selected
5. PASS: step 12 remains selected
6. switch Root Causes → Solutions
7. PASS: linked pain point remains selected where applicable
```

**Visualization**

```text
PASS: frustration overlay can be selected independently from confusion overlay.
PASS: selecting a pain element shows its behavioral impact.
PASS: video can seek to a linked evidence timestamp.
```

### Exit criterion

A non-developer can explain what happened, why it hurt, where it hurt, and what alternatives were proposed from the UI alone.

---

## Stage 9 — Custom job packages and Gradio API

### Deliverables

- predefined packages;
- custom DAG schema;
- DAG validation;
- fan-out/fan-in;
- resume;
- replay stage;
- explicit Gradio `api_name`s.

### Required tests

**DAG validation**

```text
PASS: valid custom pipeline accepted.
PASS: cycle rejected.
PASS: unknown job type rejected.
PASS: incompatible artifact mapping rejected.
```

**Fan-out**

```text
PASS: one persona batch of 3 creates 3 behavior jobs.
PASS: 3 behavior jobs can create 3 Journey jobs.
PASS: final report waits for required dependencies.
```

**Replay**

```text
PASS: rerun Eyeson from existing screen artifacts without rerunning persona or journey.
PASS: rerun report from existing artifacts.
```

**Gradio API**

Using `gradio_client`:

```text
PASS: /generate_persona_batch callable.
PASS: /run_journey_only callable.
PASS: /run_combined_test callable.
PASS: /run_custom_pipeline callable.
PASS: returned pipeline_run_id can be polled through FastAPI.
```

### Exit criterion

External code can treat Gradio as a convenience API while all canonical state remains in FastAPI.

---

## Stage 10 — Cohort testing, hardening, and production readiness

### Deliverables

- multi-user concurrency;
- iteration support;
- aggregate root-cause analysis;
- queue limits;
- timeouts;
- auth;
- artifact retention;
- Langfuse adapter;
- GitHub exporter;
- load tests.

### Required tests

**Cohort**

Run:

```text
10 personas × 2 iterations
```

Required:

```text
PASS: 20 journey runs have unique run IDs.
PASS: no browser state leakage between isolated runs where isolation requested.
PASS: aggregate report counts all successful/failed/abandoned runs correctly.
PASS: pain-point aggregation preserves original source users.
```

**Resilience**

```text
PASS: kill a worker mid-job; attempt is marked interrupted/failed and can retry.
PASS: restart API; pipeline state survives.
PASS: failed Eyeson job does not destroy JourneyTest artifacts.
PASS: RAG outage results in grounding=failed, not full pipeline failure unless grounding was configured as required.
```

**Load**

Define an initial target, e.g.:

```text
5 simultaneous Journey runs
20 concurrent Eyeson screenshot jobs
```

and require no lost job events/artifacts.

**Security**

```text
PASS: unauthenticated protected production endpoint rejected.
PASS: path traversal artifact request rejected.
PASS: raw secrets are redacted from text artifacts.
```

### Exit criterion

The system is suitable for controlled multi-user deployments and repeatable UX experiments.

---

# 30. Required automated test suites

## Python

Use:

- `pytest`
- `pytest-asyncio`
- `httpx` test client
- Pydantic validation
- coverage

Required directories:

```text
tests/unit
tests/contract
tests/integration
tests/e2e
```

## TypeScript

Use:

- JourneyTest's compatible test runner (Vitest);
- TypeScript typecheck;
- fixture browser tests.

## UI

Use Playwright against mounted Gradio.

Do not rely only on unit-testing Gradio callback functions.

## Contract tests

For every stage:

```text
producer output schema
=
consumer accepted input schema
```

must be tested.

---

# 31. CI gates

Every pull request MUST pass:

```text
Python lint/typecheck
Python unit tests
Python contract tests
TypeScript typecheck
TypeScript unit tests
OpenAPI generation
OpenAPI/TS client drift check
Docker builds
Gradio tab smoke test
fixture e2e quick test
```

Nightly/extended:

```text
TinyTroupe real-model smoke
DSPy evaluation
JourneyTest browser suite
Eyeson visual suite
10×2 cohort test
RAG fixture retrieval
report screenshot regression
```

---

# 32. Versioning

Every service exposes:

```text
GET /version
```

Example:

```json
{
  "service": "journey-worker",
  "version": "0.3.0",
  "git_sha": "...",
  "dependencies": {
    "journeytest-core": "0.1.2",
    "agent-browser": "..."
  }
}
```

Artifacts MUST record producer version.

---

# 33. Recommended local Docker Compose services

```text
api
gradio
persona-worker
semantic-worker
journey-worker
eyeson-worker
knowledge-worker
report-worker
postgres
redis
```

Optional:

```text
minio
langfuse/exporter
```

Do not install all runtimes into one container.

---

# 34. Migration from current `aux_backup`

## Step A

Freeze current UI tab behavior with Playwright smoke tests.

## Step B

Extract FastAPI app from the bottom of `app.py` into `apps/api/main.py`.

## Step C

Move each Gradio tab into a separate module.

## Step D

Create an `OrchestratorClient` used by all callbacks.

## Step E

Replace direct GitHub branch/session operations in the primary workflow with FastAPI sessions/jobs.

## Step F

Keep GitHub export as an explicit optional job.

## Step G

Replace runtime TinyTroupe cloning/patching with pinned package dependency.

## Step H

Move JourneyTest into its Node 24 worker container.

## Step I

Import Eyeson engine and remove its separate browser capture from combined runs.

---

# 35. Data lineage example

A developer MUST be able to inspect this chain:

```text
Session ses_1
│
├── Job job_1 persona.generate.batch
│     └── Artifact art_persona_1
│
├── Job job_2 behavior.compile
│     input: art_persona_1
│     └── Artifact art_behavior_1
│
├── Job job_3 agent-runtime.prepare
│     input: art_behavior_1
│     └── Artifact art_runtime_1
│
├── Job job_4 journey.run
│     input: art_runtime_1
│     ├── art_run_json
│     ├── art_video
│     ├── art_screen_001
│     ├── art_screen_002
│     └── art_behavior_events
│
├── Job job_5 eyeson.screen.analyze
│     input: art_screen_001
│     └── art_eyeson_001
│
├── Job job_6 eyeson.screen.analyze
│     input: art_screen_002
│     └── art_eyeson_002
│
├── Job job_7 pain.resolve
│     inputs: journey + behavior + Eyeson
│     └── art_pain_points
│
├── Job job_8 knowledge.search
│     input: art_pain_points
│     └── art_knowledge
│
├── Job job_9 alternatives.generate
│     inputs: pain + knowledge
│     └── art_alternatives
│
└── Job job_10 report.build
      inputs: all above
      ├── report.md
      └── report.html
```

No hidden in-memory dependency is permitted for this chain.

---

# 36. Example developer acceptance scenario

Fixture persona:

```text
high persistence
low patience
high anger reactivity
moderate digital confidence
```

Fixture page:

`/ambiguous-save`

Expected test narrative:

1. Synthetic user clicks Save.
2. Page gives weak/incomplete feedback.
3. Waiting tolerance is exceeded.
4. Frustration increases.
5. Coping policy selects retry.
6. JourneyTest records repeated action.
7. Eyeson receives the exact screenshot.
8. Eyeson attributes pain to Save/feedback region.
9. Pain resolver creates a high-confidence issue.
10. Null knowledge provider marks recommendation ungrounded/not-configured.
11. Alternative generator proposes persistent save-state feedback.
12. Report renders:
    - observed events;
    - behavioral state delta;
    - implicated element;
    - diagnosis;
    - alternative;
    - grounding status.
13. UI switches between Journey and UX Feedback while preserving the same step.

This scenario MUST be part of the end-to-end CI suite by Stage 8.

---

# 37. Roadmap after core implementation

## RAG

- ingest curated UX corpora;
- source/version tracking;
- hybrid semantic + keyword retrieval;
- internal knowledge collections;
- evidence citation UI.

## Human calibration

- import real usability sessions;
- compare synthetic vs human:
  - task completion;
  - action sequences;
  - time;
  - errors;
  - retries;
  - abandonment;
  - frustration ratings;
- optimize DSPy modules against labeled data;
- calibrate native state-model coefficients.

## Alternative validation

```text
pain point
→ proposed alternative
→ render/prototype
→ rerun same personas/seeds
→ compare
```

## Design integrations

- Figma;
- Onlook;
- code-generation agents;
- automated preview deployments.

---

# 38. Definition of done for the first useful product

The first useful product is complete when a user can:

1. open the Gradio Analysis Orchestrator;
2. enter URL + task + scenario;
3. request N TinyTroupe personas;
4. inspect generated personas;
5. run a combined pipeline;
6. visually follow JourneyTest;
7. see state changes and coping decisions;
8. switch to UX Feedback on the same timestamp;
9. see Eyeson-highlighted pain elements;
10. see a root-cause explanation;
11. see structured alternative solutions;
12. see grounding status even when RAG is not configured;
13. export a developer handoff;
14. invoke each major step individually through FastAPI;
15. invoke predefined/custom job packages through the Gradio API;
16. replay Eyeson/report generation without rerunning the browser journey.

---

# 39. Reference repositories and current implementation facts

- Product/UI base: https://github.com/JsonLord/aux_backup
- Eyeson: https://github.com/JsonLord/eyeson
- JourneyTest: https://github.com/Jules-Astier/journeytest-core
- TinyTroupe upstream: https://github.com/microsoft/TinyTroupe
- Existing TinyTroupe fork used by `aux_backup`: https://github.com/JsonLord/TinyTroupe
- AI-UX reference only: https://github.com/JsonLord/AI-UX

Current-state facts relevant to migration:

- `aux_backup` is Python/Gradio/FastAPI and currently keeps most UI/business logic in one large `app.py`.
- `aux_backup` currently uses Python 3.12 and installs Node 22 in its Docker image.
- JourneyTest currently declares Node >=24 and is a TypeScript package.
- JourneyTest already produces raw run evidence including JSON, Markdown/dashboard, video, screenshots, snapshots, UI-change evidence, and timeline events.
- Eyeson currently uses Node/Express with Puppeteer, Sharp, Gemini, SQLite, and Jest.
- TinyTroupe is a Python package and supports Python >=3.10.
- Existing `aux_backup` tabs already cover most desired top-level product areas; the main change is to make them API-driven and evidence-synchronized rather than branch-polling/business-logic-heavy.

---

# 40. Final architectural rule

The platform MUST preserve this separation:

```text
TinyTroupe
    WHO is the user?

DSPy semantic compiler
    How should this persona be translated into structured behavioral priors?

Native behavior runtime
    How do those priors mechanically change state, timing, mistakes, coping and limitations?

JourneyTest
    What did the user do, and what actually happened in the browser?

Eyeson
    Where did the interface cause pain, and what visible/interaction mechanism explains it?

UX Knowledge Grounder
    What credible knowledge supports that diagnosis?

Alternative Generator
    What could be changed?

Report/UI
    How can a human inspect the complete causal chain?
```

The canonical causal chain exposed by the product is:

```text
PERSONA
→ BEHAVIOR PROFILE
→ USER STATE
→ OBSERVATION
→ ACTION
→ UI RESPONSE
→ EXPERIENCE EVENT
→ STATE CHANGE
→ COPING DECISION
→ PAIN POINT
→ ELEMENT ATTRIBUTION
→ UX DIAGNOSIS
→ KNOWLEDGE GROUNDING
→ ALTERNATIVE
→ REPORT
```

Every arrow MUST be inspectable through a job record, API response, artifact reference, or event.
