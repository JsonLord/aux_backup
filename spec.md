# Synthetic UX Testing Platform — Full Application Specification

**Status:** Draft implementation specification  
**Target host application:** `JsonLord/eyeson` (`ux-analyst-ai`)  
**Browser/runtime dependency:** `Jules-Astier/journeytest-core`  
**Persona engine:** `microsoft/TinyTroupe`  
**Semantic program layer:** DSPy  
**Optional reference/donor:** `JsonLord/AI-UX`  
**Primary goal:** Run synthetic, persona-aware user journeys against live websites, observe behavior and visual experience, diagnose element-level UX pain, generate grounded alternatives, and present all evidence in a replayable report.

---

## 1. Executive summary

The application combines four responsibilities that must remain architecturally distinct:

1. **Persona generation** — create plausible synthetic users with goals, preferences, experience and personality using TinyTroupe.
2. **Behavior simulation** — convert stable persona traits plus explicit functional abilities into reproducible dynamic behavior such as patience, retry tolerance, frustration growth, help seeking, impulsive retry and abandonment.
3. **Live user-journey execution** — use JourneyTest-core as the only authoritative browser/controller, including action execution, semantic page snapshots, screenshots, UI-change observation, video and journey verdicts.
4. **UX diagnosis and remediation** — use Eyeson to analyze the exact screenshots and interface evidence produced by JourneyTest, connect observed frustration to UI elements, explain likely UX mechanisms, visualize pain, retrieve UX knowledge through a future RAG provider, and propose alternative solutions.

The product must expose two primary report modes over the same evidence:

- **User Journey** — what the synthetic person did, perceived and experienced.
- **UX Feedback** — where the interface caused friction, why, how severe it was, and what design changes could reduce it.

Both modes must remain synchronized to the same user, journey step, timestamp and screenshot.

The central architectural rule is:

> **JourneyTest owns the live browser. Eyeson never starts a second browser to re-create the tested state.**

Every screenshot, DOM/accessibility snapshot and UI-change record is captured once by JourneyTest and then distributed to behavior analysis and Eyeson.

---

## 2. Goals

### 2.1 Product goals

The application shall:

- Accept a website URL and a user task.
- Generate one or more synthetic users.
- Allow multiple iterations per synthetic user.
- Support adjustable scenario/context and randomness.
- Allow explicit functional limitations and behavioral traits.
- Execute the task on the real website.
- Record browser video and step evidence.
- Maintain an explicit dynamic user state during the run.
- Detect frustration, confusion, trust loss, effort, fatigue and progress changes.
- Apply coping policies such as retry, reread, wait, explore, seek help, backtrack, impulsive retry and abandon.
- Visually simulate selected perceptual limitations where configured.
- Feed captured screenshots and semantic evidence to Eyeson.
- Attribute pain to one or more UI elements with confidence.
- Produce frustration/confusion/effort overlays on screenshots.
- Generate structured UX diagnoses.
- Create alternative design solutions.
- Keep a RAG/UX knowledge grounding extension point from the first implementation.
- Generate a final replayable report and machine-readable `run.json`.
- Aggregate findings across users and iterations.
- Preserve deterministic replay where a seed and model version are fixed.

### 2.2 Research goals

The platform should make later calibration against real usability studies possible. It must therefore preserve:

- persona inputs;
- compiled behavioral parameters;
- random seeds;
- model/version identifiers;
- every observed browser event used to update state;
- all deterministic state transitions;
- inferred appraisals with confidence;
- selected coping actions and probability distributions;
- screenshots and element boxes;
- final diagnoses and grounding references.

### 2.3 Non-goals for v1

The first production version does **not** need to:

- claim clinical fidelity for disability simulation;
- infer medical limitations directly from age or demographics;
- replace real human usability studies;
- allow multiple autonomous browser agents to compete for control;
- run a second Eyeson crawler in parallel with JourneyTest;
- require a production vector database before the RAG roadmap phase;
- generate a fully working replacement application for every UX recommendation;
- use AI-UX as a second journey execution engine.

---

## 3. Source repositories and ownership boundaries

### 3.1 `Jules-Astier/journeytest-core`

**Role:** authoritative browser runtime, action execution, semantic observation, journey verdict, artifacts and base reporting.

Current code anchors observed in the repository:

- `src/core/schemas.ts` — core Zod schemas and run/result types.
- `src/runner/runJourney.ts` — journey orchestration and final artifact writing.
- `src/runner/events.ts` — event stream.
- `src/directors/` — agent/director implementations.
- `src/drivers/` — browser abstraction and concrete browser driver.
- `src/reporters/markdown.ts` — Markdown report renderer.
- `src/reporters/dashboard.ts` — single-run evidence dashboard.
- `src/reporters/suiteDashboard.ts` — suite/aggregate dashboard.
- `src/reporters/runComparison.ts` — run comparison.
- `src/video/` — journey video support.

**Must own:**

- single live browser session;
- navigation, click, fill, type, key, scroll and wait;
- semantic snapshot and element references;
- before/after UI evidence;
- screenshots/video;
- task completion verdict;
- action/timeline event emission;
- authoritative dynamic behavior state during a journey.

**Must not own:**

- TinyTroupe internals;
- DSPy program definitions;
- deep visual UX critique;
- UX knowledge retrieval;
- visual design solution rendering.

---

### 3.2 `JsonLord/eyeson`

**Role:** product host, UX analysis layer, report enrichment and final frontend.

The repository already contains a full application under `ux-analyst-ai/` with:

- `backend/`
- `frontend/`
- `cli/`
- `mcp-server/`
- `docker-compose.yml`

The backend is already service-oriented, with `backend/services`, `backend/routes`, `backend/interfaces`, `backend/core` and a central bootstrap/server.

**Eyeson becomes the integration host application.** Do not create another top-level web app unless necessary.

**Must own:**

- experiment configuration API;
- starting/stopping orchestrated runs;
- multi-user/multi-iteration orchestration;
- artifact indexing and report persistence;
- Eyeson visual analysis;
- pain-point resolution;
- UX classification;
- solution generation;
- RAG provider interface;
- frontend configuration screen;
- live/replay frontend;
- user-journey and UX-feedback report views;
- aggregate root-cause view.

**Must not own:**

- a separate browser crawler for journey states;
- an independent user-journey agent loop.

Existing URL-based Eyeson analysis may remain for standalone legacy usage, but the integrated product path must accept **captured evidence**, not only URLs.

---

### 3.3 `microsoft/TinyTroupe`

**Role:** persona identity and high-level psychological/social characterization.

Relevant current package areas include:

- `tinytroupe/agent/tiny_person.py`
- `tinytroupe/agent/mental_faculty.py`
- `tinytroupe/agent/memory.py`
- `tinytroupe/agent/grounding.py`
- `tinytroupe/profiling.py`
- `tinytroupe/factory/`
- `tinytroupe/experimentation/`

TinyTroupe shall be installed as a Python dependency in the persona runtime. It should not receive raw browser ownership in the default architecture.

**Must own:**

- persona narrative/profile;
- goals and motivations;
- personality;
- preferences;
- knowledge/skills;
- technology familiarity;
- optionally explicit high-level attitudes or coping tendencies.

**Must not infer as fact:**

- visual impairment from age alone;
- motor impairment from age alone;
- cognitive impairment from age alone.

Functional abilities are a separate explicit model.

---

### 3.4 DSPy

**Role:** semantic compilation, appraisal and judgment where LLM reasoning adds value.

DSPy is a Python library in the persona runtime, not another browser agent.

Use DSPy for:

- TinyTroupe persona -> numeric/structured behavior-profile compilation;
- ambiguous experience-event appraisal;
- persona visual judgment;
- UX diagnosis/classification;
- later prompt/demo optimization against human-study metrics.

Do not use DSPy for:

- frustration arithmetic;
- timers;
- waiting tolerance execution;
- random sampling;
- pointer noise;
- visual color-transform code;
- browser execution;
- hard stop conditions.

---

### 3.5 `JsonLord/AI-UX`

**Role in this architecture:** optional reference/donor only.

AI-UX is a Django-based application with Figma-oriented journey simulation. It must **not** become a second live journey engine.

Potential reusable concepts:

- visual storytelling of a journey;
- generated cursor/click overlays;
- before/after solution presentation;
- Figma/prototype export in a later roadmap phase.

For v1, no runtime dependency is required.

---

## 4. Recommended deployment topology

Use Eyeson's existing `ux-analyst-ai` as the host application.

```text
Browser / user
     |
     v
Eyeson frontend
     |
     v
Eyeson backend / experiment orchestrator (Node)
     |
     +--------------------------+
     |                          |
     v                          v
JourneyTest-core            Persona runtime
(Node/TypeScript)           (Python)
     |                          |
     |                          +-- TinyTroupe
     |                          +-- DSPy
     |
     +-- agent-browser / browser driver
     |
     +-- screenshots / DOM / a11y / UI changes / video
     |
     +-------------------------------+
                                     |
                                     v
                              Eyeson analysis services
                                     |
                                     +-- pain-point resolver
                                     +-- visual critique
                                     +-- alternative generator
                                     +-- UXKnowledgeProvider (RAG placeholder)
                                     |
                                     v
                              Enriched run/report store
```

### 4.1 Recommended service model

For local development:

- `eyeson-backend` — Node service.
- `eyeson-frontend` — existing frontend.
- `persona-runtime` — Python process.
- JourneyTest runs **inside or as a child worker of the Eyeson backend**.
- Artifacts stored on shared local filesystem volume.

For production:

- Eyeson backend API.
- one or more JourneyTest workers.
- persona runtime service.
- object storage adapter for artifacts.
- optional queue adapter for deep Eyeson analysis.

Do not require Redis for the first local complete version. Define a `JobQueue`
interface with an in-memory implementation. Production uses externally hosted Redis
and Celery; neither durable workers nor Redis/PostgreSQL run inside the HF Space.

---

## 5. Dependency integration strategy

### 5.1 JourneyTest-core

Resolved baseline: exact npm dependency
`@baguette-studios/journeytest-core@0.1.2`, release commit
`9139d581fc6a882257ea4c46bdf16d59547c0ae5`. Use its package API before considering
a fork. If extension points prove insufficient, fork from this commit only.

During development, pin a commit or local package path.

Recommended long-term approach:

1. Fork `journeytest-core` into the project organization.
2. Keep upstream remote configured.
3. Publish the fork as a private/internal npm package or use a pinned Git dependency.
4. Never depend on unpinned `main` in production.

The Eyeson backend should import JourneyTest via package API, not shell out to its CLI for the integrated path.

### 5.2 TinyTroupe

Pin `microsoft/TinyTroupe` v0.7.0 at commit
`a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4` in the persona-runtime lockfile. Do not
patch installed TinyTroupe files at startup. Blablador compatibility belongs in the
persona adapter; fork from this commit only if an adapter cannot provide it.

### 5.3 DSPy

Pin the version in the same Python environment as TinyTroupe.

DSPy is gated by parity evaluation and is not the default semantic engine. The
default direct baseline is `DirectLLMSemanticEngine` using the existing
OpenAI-compatible Helmholtz Blablador provider with model `alias-huge`. CI uses a
deterministic mock engine. Domain schemas never depend on provider response formats.

### 5.4 AI-UX

No runtime dependency in v1. If later reused, extract only the relevant rendering/prototyping component behind an interface.

### 5.5 Resolved deployment, tenancy, storage and migration defaults

- HF Spaces hosts Gradio, the thin HTTPS API proxy, and HF OAuth/OIDC only. Durable
  FastAPI/Celery/Journey/Eyeson/persona/report workers run outside the Space with
  externally hosted PostgreSQL and Redis.
- Stable user identity is the HF OIDC subject. Every session, job and artifact has a
  `workspace_id` and `owner_user_id`; workspaces are personal or HF organization
  workspaces. Service calls use separate service credentials. Object keys are
  prefixed `workspace/session/`.
- Cloudflare R2 is the default implementation of the generic S3-compatible artifact
  interface. Raw evidence retention is 30 days, structured reports/job metadata 180
  days, and pinned runs indefinite. Direct multipart uploads are limited to 25 MB;
  larger objects use presigned uploads, with an initial 1 GB object maximum.
- Existing GitHub-branch sessions remain read-only for at least one major migration
  cycle through `LegacyGitHubSessionProvider`. New work never writes analysis state
  to branches. `POST /v1/legacy/github/import` ingests a legacy branch as a new
  session without rerunning it.
- Gradio callback migration order is Analysis Orchestrator, Report Viewer, Live
  Monitoring, Persona & Behavior Trace, Cohort Pain Maps, Full New UI, Presentation
  Carousel, Developer Handoff/Agents.txt, System, then Alternative Styling.
- Eyeson provenance is captured as a squashed subtree import with original URL and
  commit recorded in `docs/upstream-sources.md`; it need not stay synchronized as a
  permanent subtree.

---

## 6. Product input model

The application input screen shall include the already planned experiment controls:

- Generate visual solutions: yes/no.
- Number of simulated users.
- Use-case scenario.
- Iterations per synthetic user.
- Heat/randomness.
- Number of screens.
- Task to perform.
- Website link.
- Preferred classification system.

`Simulated User params` is a section/group, not a single input.

### 6.1 Additional recommended controls

#### Persona generation

- Persona source:
  - TinyTroupe generated;
  - user supplied;
  - preset cohort.
- Persona seed.
- Persona diversity: low / medium / high.

#### Functional abilities

Default mode: `Auto / Configure`.

When configuring:

- vision profile;
- color-vision profile;
- contrast sensitivity;
- visual acuity transform strength;
- pointer precision;
- movement speed;
- processing speed;
- working-memory capacity;
- reading speed;
- assistive strategy availability.

Do not automatically bind these to age.

#### Behavioral traits

Advanced configuration:

- patience;
- persistence;
- irritability;
- anger reactivity;
- anger recovery;
- impulsivity;
- ambiguity tolerance;
- first-failure tolerance;
- repeat-failure tolerance;
- self-efficacy;
- digital confidence;
- help seeking;
- exploration;
- verification tendency;
- risk tolerance.

Most users should leave these at generated defaults.

#### Context

- task importance;
- time pressure;
- device type;
- environmental distraction;
- network profile if simulated;
- authentication state or preconditions.

#### Execution limits

- max actions;
- max wall-clock runtime;
- allowed origins;
- allow abandonment;
- allow repeated mistakes;
- allow help seeking;
- allow browser back;
- allow external navigation.

---

## 7. Core experiment entities

### 7.1 ExperimentConfig

```ts
interface ExperimentConfig {
  id: string;
  websiteUrl: string;
  task: string;
  useCaseScenario: string;

  userCount: number;
  iterationsPerUser: number;
  randomSeed: number;
  lmTemperature: number;
  maxScreens: number;
  maxActions: number;

  classificationSystem: string;
  generateVisualSolutions: boolean;

  personaConfig: PersonaGenerationConfig;
  abilityConfig: AbilityGenerationConfig;
  behaviorConfig: BehaviorGenerationConfig;
  executionPolicy: ExecutionPolicy;
}
```

### 7.2 SyntheticUserProfile

```ts
interface SyntheticUserProfile {
  id: string;
  source: "tinytroupe" | "manual" | "preset";

  persona: PersonaSpec;
  abilities: FunctionalAbilitySpec;
  behavior: BehaviorProfile;

  generation: {
    seed: number;
    model: string;
    compilerVersion: string;
  };
}
```

### 7.3 PersonaSpec

Stable descriptive identity.

```ts
interface PersonaSpec {
  name?: string;
  age?: number;
  occupation?: string;
  education?: string;
  context?: string;
  goals: string[];
  motivations: string[];
  preferences: string[];
  beliefs?: string[];
  skills: string[];
  technologyExperience: string;
  personality: Record<string, unknown>;
}
```

### 7.4 FunctionalAbilitySpec

```ts
interface FunctionalAbilitySpec {
  vision: {
    colorVision: "typical" | "protanopia" | "deuteranopia" | "tritanopia" | "custom";
    acuity: number;
    contrastSensitivity: number;
    glareSensitivity?: number;
  };

  motor: {
    pointerPrecision: number;
    movementSpeed: number;
    dragReliability: number;
  };

  cognition: {
    processingSpeed: number;
    workingMemoryItems: number;
    distractionSusceptibility: number;
  };

  reading: {
    wordsPerMinute: number;
  };

  compensatoryStrategies: string[];
}
```

### 7.5 BehaviorProfile

```ts
interface BehaviorProfile {
  seed: number;

  patience: number;
  persistence: number;
  irritability: number;
  angerReactivity: number;
  angerRecovery: number;
  impulsivity: number;

  ambiguityTolerance: number;
  failureTolerance: number;
  repeatFailureTolerance: number;

  selfEfficacy: number;
  digitalConfidence: number;
  helpSeeking: number;
  exploration: number;
  verificationTendency: number;
  riskTolerance: number;
}
```

All normalized values are `0..1` unless otherwise stated.

---

## 8. Dynamic user state

The authoritative user state lives in JourneyTest/TypeScript and changes after every meaningful event.

```ts
interface UserState {
  step: number;
  elapsedMs: number;

  frustration: number;
  anger: number;
  confusion: number;
  trust: number;
  confidence: number;

  cognitiveEffort: number;
  physicalEffort: number;
  fatigue: number;
  perceivedProgress: number;

  consecutiveFailures: number;
  repeatedEventCounts: Record<string, number>;
  recentElementIds: string[];
  rememberedFacts: string[];

  copingMode:
    | "normal"
    | "cautious"
    | "persistent"
    | "impulsive"
    | "help_seeking"
    | "abandoning";
}
```

### 8.1 Why state must be native code

State transitions must be:

- reproducible;
- inspectable;
- fast;
- versionable;
- testable without an LLM;
- calibratable later against human data.

An LLM may classify what happened, but it must not be the sole authority for `frustration = 0.71`.

---

## 9. Experience events

All browser outcomes are normalized to `ExperienceEvent` objects before state updates.

```ts
interface ExperienceEvent {
  id: string;
  stepId: string;
  timestampMs: number;

  type:
    | "waiting"
    | "success"
    | "software_failure"
    | "validation_failure"
    | "navigation_failure"
    | "user_error"
    | "motor_error"
    | "perception_failure"
    | "ambiguous_feedback"
    | "data_loss"
    | "recovery"
    | "progress";

  severity: number;
  durationMs?: number;
  goalBlocked: boolean;
  progressVisible: boolean;

  attribution: {
    software: number;
    interface: number;
    capability: number;
    user: number;
  };

  recoveryQuality: number;
  repeatKey?: string;
  evidenceRefs: string[];
  classifierConfidence: number;
}
```

Attribution values should approximately sum to `1.0`.

### 9.1 Native vs DSPy event classification

Use native rules for obvious cases:

- HTTP/network failure;
- no DOM change after a timed action;
- explicit validation error;
- browser navigation failure;
- clear success marker.

Use DSPy only when classification is ambiguous.

```text
Native classifier
  |
  +-- confidence >= threshold --> ExperienceEvent
  |
  +-- ambiguous ----------------> DSPy AppraiseUXEvent
```

---

## 10. Behavior state reducer

Implement pure functions in TypeScript.

Suggested path in the JourneyTest fork:

```text
src/behavior/
  schemas.ts
  types.ts
  initialState.ts
  stateReducer.ts
  waitTolerance.ts
  copingPolicy.ts
  seededRandom.ts
  behaviorController.ts
  experienceClassifier.ts
  physicalModifiers.ts
```

### 10.1 State-update principles

State updates may depend on:

- event severity;
- repetition count;
- goal blockage;
- recovery quality;
- perceived responsibility;
- task importance;
- time pressure;
- user behavior traits;
- previous emotional momentum.

Repeated events should increase impact non-linearly.

All constants must be versioned and clearly labeled as simulation coefficients until empirically calibrated.

### 10.2 Frustration momentum

A new issue encountered when frustration is already high may create a larger behavioral effect than the same issue at the beginning of a journey.

The reducer should support emotional persistence and recovery.

### 10.3 Separate effort from anger

Track at least:

- frustration;
- cognitive effort;
- physical effort;
- temporal cost.

A user can successfully complete a task without becoming angry but still experience excessive effort.

---

## 11. Waiting tolerance

Waiting tolerance is executable behavior, not prompt prose.

The controller computes a user-specific tolerance from:

- baseline tolerance;
- patience;
- current frustration;
- task importance;
- time pressure;
- visible progress;
- expected complexity;
- current trust.

Visible progress and clear expectations should increase waiting tolerance.

Example behavior:

```text
8 seconds, blank state            -> high uncertainty
8 seconds, "Uploading 72%"       -> lower uncertainty
20 seconds after "may take 30s"  -> may remain acceptable
```

The implementation must expose the computed wait threshold in evidence for debugging.

---

## 12. Coping policy

Coping is represented as a policy over the current user state.

```ts
type CopingDecision =
  | { type: "retry" }
  | { type: "reread"; durationMs: number }
  | { type: "wait"; durationMs: number }
  | { type: "explore" }
  | { type: "seek_help" }
  | { type: "backtrack" }
  | { type: "impulsive_retry"; repetitions: number }
  | { type: "abandon"; reason: string };
```

### 12.1 Policy scoring

Each action receives a score from profile + state + context.

Examples:

- `retry` increases with persistence and self-efficacy.
- `reread` increases with verification tendency and confusion.
- `wait` increases with patience and perceived progress.
- `seek_help` increases with help-seeking tendency and confusion.
- `impulsive_retry` increases with impulsivity, irritability and anger.
- `abandon` increases with frustration, fatigue and time pressure and decreases with persistence and task importance.

Convert scores to probabilities using softmax or a documented alternative, then sample with a seeded RNG.

Persist the full probability distribution for every selected coping decision.

### 12.2 Coping intent vs browser action

Coping decisions are **intentions**.

JourneyTest/Pi remains responsible for semantic realization when necessary.

```text
EXPLORE
  -> Pi identifies a plausible alternative on the current page

SEEK_HELP
  -> Pi searches the currently visible interface for help/FAQ/support

BACKTRACK
  -> native browser-back when safe, or Pi chooses previous route

IMPULSIVE_RETRY
  -> deterministic action middleware repeats prior target quickly
```

---

## 13. Physical and perceptual simulation

Functional limitations must affect actual inputs/evidence where possible.

### 13.1 Color vision

Before persona visual judgment:

```text
original screenshot
  -> deterministic color-vision transform
  -> contrast/acuity transform if configured
  -> perceived screenshot
  -> multimodal persona judge
```

Keep both original and perceived screenshot.

### 13.2 Visual acuity / contrast

Implement deterministic image transforms with a versioned profile.

Do not call them clinically exact. In UI/report label them as simulated perception profiles.

### 13.3 Motor precision

Semantic `click(@e17)` always succeeds at the intended element and cannot simulate pointer error.

When motor simulation is enabled:

1. retrieve the element bounding box;
2. calculate intended coordinates;
3. apply seeded pointer noise;
4. use low-level mouse movement/down/up if supported by the driver;
5. observe the actual result.

Extend JourneyTest's browser driver only where necessary.

### 13.4 Reading speed

Estimate reading/dwell time from visible word count and configured words per minute.

Personality determines whether the actor reads, skims or abandons; reading speed determines the cost when reading occurs.

### 13.5 Working memory

Do not merely tell the model "you have poor memory".

Limit the behavioral context exposed to the actor:

- retain current task goal;
- retain a bounded set of recent relevant facts;
- drop older interface facts according to working-memory rules;
- allow compensatory strategies such as rereading or backtracking.

---

## 14. DSPy architecture

### 14.1 Why use DSPy

DSPy is useful because the application has several repeated semantic transformations that can later be optimized against real usability data.

Use native code for deterministic state and DSPy for semantic compilation/judgment.

Recommended split:

```text
NATIVE TYPESCRIPT/PYTHON
- browser execution
- timers
- state reducer
- coping probabilities
- physical simulation
- random sampling
- evidence persistence

DSPy/LLM
- TinyPersona -> BehaviorProfile
- ambiguous event appraisal
- persona visual judgment
- UX diagnosis/classification
- alternative rationale
- later optimization against human data
```

### 14.2 DSPy module: persona compiler

```python
class CompileBehaviorProfile(dspy.Signature):
    """
    Convert a synthetic persona into structured web-interaction priors.
    Do not infer medical or physical impairments from demographics alone.
    """

    tiny_person: dict = dspy.InputField()
    scenario: str = dspy.InputField()

    patience: float = dspy.OutputField()
    persistence: float = dspy.OutputField()
    irritability: float = dspy.OutputField()
    anger_reactivity: float = dspy.OutputField()
    anger_recovery: float = dspy.OutputField()
    failure_tolerance: float = dspy.OutputField()
    repeat_failure_tolerance: float = dspy.OutputField()
    ambiguity_tolerance: float = dspy.OutputField()
    help_seeking: float = dspy.OutputField()
    exploration: float = dspy.OutputField()
    digital_confidence: float = dspy.OutputField()
    verification_tendency: float = dspy.OutputField()
```

Compile once per synthetic user, not once per browser step.

### 14.3 DSPy module: ambiguous appraisal

```python
class AppraiseUXEvent(dspy.Signature):
    persona: dict = dspy.InputField()
    current_state: dict = dspy.InputField()
    intended_action: dict = dspy.InputField()
    before_state: str = dspy.InputField()
    after_state: str = dspy.InputField()
    ui_changes: str = dspy.InputField()

    event_type: str = dspy.OutputField()
    severity: float = dspy.OutputField()
    goal_blocked: bool = dspy.OutputField()
    software_attribution: float = dspy.OutputField()
    interface_attribution: float = dspy.OutputField()
    capability_attribution: float = dspy.OutputField()
    user_attribution: float = dspy.OutputField()
    recovery_quality: float = dspy.OutputField()
    explanation: str = dspy.OutputField()
    confidence: float = dspy.OutputField()
```

### 14.4 DSPy module: persona visual judge

```python
class PersonaVisualJudge(dspy.Signature):
    persona: dict = dspy.InputField()
    behavior_profile: dict = dspy.InputField()
    user_state: dict = dspy.InputField()
    screenshot: dspy.Image = dspy.InputField()
    accessibility_tree: str = dspy.InputField()
    interface_elements: str = dspy.InputField()
    task: str = dspy.InputField()

    noticed: list[str] = dspy.OutputField()
    missed_or_overlooked: list[str] = dspy.OutputField()
    confusing_elements: list[str] = dspy.OutputField()
    perceived_progress: float = dspy.OutputField()
    visual_confidence: float = dspy.OutputField()
    perceived_trust: float = dspy.OutputField()
    issue_signals: list[str] = dspy.OutputField()
```

### 14.5 Do not add a second DSPy ReAct browser agent

JourneyTest's existing agent/director loop remains the only navigation agent.

DSPy returns structured semantic information to that loop.

---

## 15. Persona runtime service

Create a new Python service inside Eyeson or as a sibling directory:

```text
ux-analyst-ai/persona-runtime/
  pyproject.toml
  app.py
  models/
    persona.py
    behavior_profile.py
    ux_event.py
    visual_judgement.py
  tinytroupe_adapter/
    factory.py
    serializer.py
  dspy_programs/
    compile_persona.py
    appraise_event.py
    visual_judge.py
    ux_diagnosis.py
  transport/
    jsonl.py
    http.py          # optional later
  tests/
```

### 15.1 Transport

For the first complete local application, use a long-lived Python subprocess speaking newline-delimited JSON over stdin/stdout.

Reasons:

- minimal infrastructure;
- easy Docker integration;
- no extra service discovery;
- lower latency than spawning Python per call.

Define a provider interface in Node so HTTP can replace JSONL later.

### 15.2 Commands

#### `initialize_persona`

Input:

```json
{
  "method": "initialize_persona",
  "sessionId": "...",
  "scenario": "...",
  "personaConfig": {},
  "abilityConfig": {},
  "seed": 42
}
```

Output:

```json
{
  "persona": {},
  "behaviorProfile": {},
  "abilities": {}
}
```

#### `appraise_event`

Only called when native classification is below confidence threshold.

#### `judge_visual_perception`

Called synchronously only when the actor requires persona-specific visual perception.

#### `diagnose_pain_point`

May be called during report enrichment.

---

## 16. JourneyTest integration changes

### 16.1 `src/core/schemas.ts`

Extend the tester profile or run context with an **optional** simulation section. Preserve backward compatibility.

Add schemas for:

- `BehaviorProfile`;
- `FunctionalAbilitySpec`;
- `UserState`;
- `ExperienceEvent`;
- `CopingDecision`;
- `BehaviorTransition`;
- enriched run UX analysis reference.

Do not force users of upstream JourneyTest to configure synthetic behavior.

### 16.2 `src/runner/runJourney.ts`

Instantiate `BehaviorController` when a simulation profile is present.

Conceptually:

```ts
const behavior = options.profile.simulation
  ? new BehaviorController(options.profile.simulation, recorder)
  : undefined;

const result = await runDirectorWithTimeout({
  context: {
    journey,
    profile,
    behavior,
    browser,
    recorder,
    artifacts,
  }
});
```

At finalization, provide an extension hook before reports are rendered:

```ts
const enriched = options.runEnricher
  ? await options.runEnricher.enrich(baseResult)
  : baseResult;
```

### 16.3 `src/runner/events.ts`

Add events such as:

- `behavior.state.changed`;
- `behavior.coping.selected`;
- `experience.event.created`;
- `evidence.screenshot.created`;
- `evidence.snapshot.created`;
- `ux.analysis.requested`;
- `ux.analysis.completed`.

These events power live UI and report synchronization.

### 16.4 Browser tool middleware

Wrap existing actions around behavior hooks:

```text
BehaviorController.beforeAction
  -> optional hesitation/delay/motor modification
  -> existing JourneyTest action
  -> existing UI-change recorder
  -> ExperienceClassifier
  -> BehaviorController.apply(event)
  -> CopingPolicy
  -> publish transition evidence
```

### 16.5 `DirectorRunContext`

Add optional:

```ts
behavior?: BehaviorController;
```

### 16.6 Agent observations

The agent may receive an auditable behavior summary after actions:

```text
Observed:
No navigation occurred. Spinner was visible for 5.4 seconds.

Synthetic-user state:
frustration 0.48
confusion 0.62
trust 0.51

Selected coping intent:
EXPLORE_ALTERNATIVE
```

Do not expose hidden chain-of-thought. Only expose explicit simulation state and concise evidence-based rationale.

### 16.7 Driver extensions for motor simulation

If required, add low-level mouse operations to the browser abstraction:

- `mouseMove(x, y)`;
- `mouseDown(button)`;
- `mouseUp(button)`.

Use `getElementBox()` to calculate coordinate targets.

### 16.8 Reporter changes

Current reporter files to extend:

- `src/reporters/markdown.ts`;
- `src/reporters/dashboard.ts`;
- `src/reporters/suiteDashboard.ts`;
- optionally `src/reporters/runComparison.ts`.

The JourneyTest fork should remain able to render its original report if `uxAnalysis` is absent.

---

## 17. Evidence model

The basic unit shared between JourneyTest and Eyeson is `JourneyStepEvidence`.

```ts
interface JourneyStepEvidence {
  id: string;
  runId: string;
  userId: string;
  iterationId: string;
  step: number;
  timestampMs: number;

  action: ActionRecord;

  screenshot?: ArtifactRef;
  perceivedScreenshot?: ArtifactRef;
  accessibilitySnapshot?: ArtifactRef;
  domSnapshot?: ArtifactRef;
  semanticSnapshot?: ArtifactRef;
  uiChanges?: ArtifactRef;
  networkEvidence?: ArtifactRef;

  elementMap?: ElementMap;

  behavior?: {
    before: UserState;
    events: ExperienceEvent[];
    after: UserState;
    coping?: CopingDecision;
  };

  eyeson?: {
    status: "pending" | "processing" | "completed" | "failed";
    findings?: EyesonFinding[];
  };
}
```

### 17.1 Stable element IDs

Screenshot annotations, semantic snapshot, accessibility tree and DOM representation must share stable element IDs wherever possible.

This is mandatory for element-level pain attribution.

---

## 18. Evidence coordinator

Add an Eyeson-backend integration service:

```text
backend/services/evidenceCoordinator.js
```

or TypeScript equivalent after migration.

Responsibilities:

- index JourneyTest artifacts;
- persist step metadata;
- publish step events to live UI;
- trigger Eyeson deep analysis;
- attach analysis results to the correct step;
- maintain per-run analysis completion status.

Interface:

```ts
interface EvidenceCoordinator {
  recordAction(...): Promise<void>;
  recordScreenshot(...): Promise<void>;
  recordSnapshot(...): Promise<void>;
  recordBehaviorTransition(...): Promise<void>;
  enqueueEyesonAnalysis(...): Promise<void>;
  attachEyesonAnalysis(...): Promise<void>;
}
```

---

## 19. Eyeson integrated analysis mode

Eyeson must gain an **evidence-input API** in addition to its legacy URL-input API.

### 19.1 Two Eyeson responsibilities

#### A. Fast persona perception

Synchronous only when required by the actor.

Input:

- original screenshot;
- transformed/perceived screenshot;
- persona;
- abilities;
- task;
- semantic element map.

Output:

- noticed elements;
- missed elements;
- perceived progress;
- visual confusion;
- visual confidence;
- trust signal.

#### B. Deep UX critique

Normally asynchronous relative to the journey.

Input:

- exact JourneyTest screenshot;
- before/after evidence;
- element map;
- action;
- behavior transition;
- classification system.

Output:

- visual issues;
- interaction feedback issues;
- hierarchy issues;
- accessibility signals;
- element attribution;
- pain-point candidates;
- structured recommendations.

### 19.2 Do not block the journey on deep critique

```text
screenshot created
  -> persist
  -> enqueue deep Eyeson analysis
  -> journey continues
```

Only fast perception, when explicitly needed for actor decision-making, may block the action loop.

---

## 20. Pain-point resolution

Add to Eyeson:

```text
backend/services/painPointResolver.js
backend/services/painEpisodeAggregator.js
```

### 20.1 Pain episode

Do not report every tiny state delta as an independent UX issue.

Aggregate contiguous/repeated friction into episodes using:

- frustration growth;
- confusion growth;
- trust decline;
- repeated actions;
- repeated errors;
- backtracking;
- long waits;
- excessive effort;
- abandonment;
- repeated interaction with the same element.

### 20.2 `UXPainPoint`

```ts
interface UXPainPoint {
  id: string;
  runId: string;
  userId: string;
  stepIds: string[];

  title: string;
  summary: string;
  severity: "low" | "medium" | "high" | "critical";
  confidence: number;

  screenshotRef: string;
  videoTimestampMs: number;

  behavioralImpact: {
    frustrationDelta: number;
    confusionDelta: number;
    trustDelta: number;
    cognitiveEffortDelta: number;
    physicalEffortDelta: number;
    elapsedCostMs: number;
    retries: number;
    backtracks: number;
  };

  elements: ElementAttribution[];
  diagnosis: UXDiagnosis;
  grounding: GroundingSummary;
  alternatives: UXAlternative[];
}
```

### 20.3 Element attribution

```ts
interface ElementAttribution {
  elementId: string;
  box: BoundingBox;
  role: "trigger" | "cause" | "feedback" | "obstacle" | "recovery";
  contribution: number;
  confidence: number;
}
```

A pain point may involve multiple elements.

Use these signals:

- directly acted-on element;
- UI elements created/changed after action;
- error/status elements;
- DOM causal timing;
- visual saliency;
- before/after screenshot region;
- persona perception.

---

## 21. UX diagnosis

Eyeson diagnosis must explicitly separate four layers:

1. **Observed facts** — browser/UI facts.
2. **Behavioral effect** — state changes and user actions.
3. **Inferred mechanism** — likely UX cause with confidence.
4. **Grounded principle** — optional retrieved UX knowledge.

```ts
interface UXDiagnosis {
  rootCause: string;
  mechanism: string;
  category: string;

  observedEvidence: string[];
  behavioralEvidence: string[];
  personaInteraction: string;

  confidence: number;
}
```

Example:

```text
Observed:
- Continue clicked twice.
- No navigation for 6.4 seconds.
- Spinner appeared, then disappeared.

Behavioral effect:
- frustration +0.24
- trust -0.11
- two retries

Inference:
Insufficient system-status feedback made it unclear whether submission was accepted.

Persona interaction:
Low waiting tolerance amplified the effect.
```

---

## 22. Pain visualizations

The frontend shall support screenshot overlays by mode:

- frustration;
- confusion;
- missed/overlooked elements;
- repeated action;
- cognitive effort;
- physical effort;
- Eyeson issue severity.

### 22.1 Friction score

Element-level friction may initially be calculated from:

```text
friction contribution
= behavioral delta
  * attribution confidence
  * element contribution
```

The exact formula is a versioned simulation metric, not an empirical truth.

### 22.2 Interaction

Clicking a highlighted region must show:

- element name/role;
- number of users affected;
- state impact;
- retry/backtrack/abandon counts;
- Eyeson diagnosis;
- alternatives;
- grounding status.

---

## 23. UX knowledge grounding / RAG placeholder

Create the abstraction in v1 even if retrieval is disabled.

```ts
interface UXKnowledgeProvider {
  search(query: UXKnowledgeQuery): Promise<UXKnowledgeResult[]>;
}
```

```ts
interface UXKnowledgeQuery {
  painPoint: UXPainPoint;
  frameworks?: string[];
  elementType?: string;
  problemCategories?: string[];
  personaFactors?: string[];
}
```

```ts
interface UXKnowledgeResult {
  id: string;
  source: string;
  title: string;
  framework:
    | "wcag"
    | "nielsen"
    | "govuk"
    | "material"
    | "internal"
    | "research"
    | "other";
  principle?: string;
  content: string;
  sourceUrl?: string;
  relevance: number;
}
```

### 23.1 Default implementation

```ts
class NullUXKnowledgeProvider implements UXKnowledgeProvider {
  async search() { return []; }
}
```

Report:

```json
{
  "grounding": {
    "status": "not_configured",
    "references": []
  }
}
```

### 23.2 Future implementations

- `VectorUXKnowledgeProvider`;
- `HybridUXKnowledgeProvider`;
- `InternalResearchProvider`;
- organization design-system connector.

### 23.3 RAG design principle

Retrieval supports diagnosis; it does not decide the diagnosis from scratch.

Correct order:

```text
observed struggle
  -> diagnosis
  -> retrieve relevant knowledge
  -> refine/support recommendation
```

Avoid retrieval-first heuristic hunting.

---

## 24. Alternative solution generation

Add:

```text
backend/services/alternativeGenerator.js
backend/services/alternativeRenderer.js
```

### 24.1 `UXAlternative`

```ts
interface UXAlternative {
  id: string;
  title: string;

  strategy:
    | "copy"
    | "feedback"
    | "layout"
    | "interaction"
    | "visual"
    | "workflow"
    | "accessibility";

  proposedChange: string;
  rationale: string;
  addressesPainPointIds: string[];

  expectedImpact: {
    frustration: "lower" | "neutral";
    confusion: "lower" | "neutral";
    taskSuccess: "higher" | "neutral";
  };

  effort: "low" | "medium" | "high";
  confidence: number;

  grounding: UXKnowledgeResult[];

  visualAlternative?: {
    originalScreenshotRef: string;
    generatedArtifactRef?: string;
    targetElementIds: string[];
    provider: string;
  };
}
```

### 24.2 Generate multiple strategies

Do not return only "make it clearer".

Example for unclear processing state:

- persistent button processing state;
- contextual progress feedback;
- immediate transition with background processing.

### 24.3 Visual alternatives

When `generateVisualSolutions = true`, use a provider abstraction:

```ts
interface VisualSolutionProvider {
  render(input: VisualSolutionInput): Promise<VisualSolutionArtifact>;
}
```

Recommended MVP provider:

1. generate localized HTML/CSS alternative or component patch;
2. render in isolated sandbox;
3. capture screenshot;
4. display next to original.

This uses Eyeson's code-generation strengths and keeps the result inspectable.

Optional roadmap providers:

- image-model mockup;
- Figma export;
- AI-UX-derived prototype renderer.

Never silently imply a generated alternative was validated by real users.

---

## 25. Experiment orchestration

Eyeson backend owns experiment-level concurrency.

```text
Experiment
  -> N synthetic users
      -> M iterations/user
          -> JourneyTest run
              -> final enriched run
  -> cohort aggregation
```

### 25.1 Concurrency limits

Configure:

- max simultaneous browsers;
- max simultaneous persona-runtime calls;
- max simultaneous deep visual analyses.

Use conservative defaults to avoid browser and model overload.

### 25.2 Randomness

Separate:

- persona seed;
- behavior seed;
- JourneyTest agent/model temperature;
- physical simulation RNG;
- alternative generation temperature.

The UI's `Heat/randomness` control may map to a documented preset across these values, but raw values must be persisted.

---

## 26. Application API

Suggested Eyeson backend API.

### Experiments

`POST /api/experiments`

Create configuration.

`GET /api/experiments/:experimentId`

Get configuration and state.

`POST /api/experiments/:experimentId/start`

Start run set.

`POST /api/experiments/:experimentId/cancel`

Cancel outstanding runs.

### Runs

`GET /api/runs/:runId`

Return machine-readable enriched run.

`GET /api/runs/:runId/events`

Server-Sent Events stream for live UI.

`GET /api/runs/:runId/report`

Report metadata.

`GET /api/runs/:runId/artifacts/:artifactId`

Serve authorized artifact.

### Analysis

`POST /api/runs/:runId/reanalyze`

Re-run Eyeson analysis without repeating browser journey.

`POST /api/pain-points/:painPointId/alternatives`

Regenerate or add alternative solutions.

`POST /api/pain-points/:painPointId/ground`

Run knowledge grounding once a provider exists.

---

## 27. Live event stream

Use Server-Sent Events first; WebSocket is not required for v1.

Important event types:

```text
run.started
persona.created
journey.step.started
action.executed
evidence.created
experience.created
behavior.state.changed
coping.selected
eyeson.analysis.started
eyeson.analysis.completed
pain_point.created
alternative.created
run.completed
```

Every event includes:

- `runId`;
- `userId`;
- `iterationId`;
- `stepId` where applicable;
- sequence number;
- timestamp.

---

## 28. Frontend information architecture

### 28.1 Screen 1 — Configure experiment

Sections:

1. Target website and task.
2. Scenario/context.
3. Synthetic users.
4. Functional abilities.
5. Behavior model.
6. Analysis settings.
7. Execution limits.

Primary action: **Run UX simulation**.

### 28.2 Screen 2 — Live run

Display:

- user/persona card;
- run/iteration progress;
- current browser/video evidence;
- current action;
- current state meters;
- current coping policy;
- recent timeline;
- Eyeson analysis status.

Do not expose hidden model chain-of-thought. Expose explicit structured rationale fields only.

### 28.3 Screen 3 — Report

Primary mode switch:

```text
[ User Journey ] [ UX Feedback ]
```

Preserve in URL/query state:

- run;
- user;
- iteration;
- step;
- timestamp;
- mode.

Suggested form:

```text
/run/:runId?mode=journey&user=:userId&step=:stepId
/run/:runId?mode=ux&user=:userId&step=:stepId
```

### 28.4 User Journey mode

Primary questions:

- Did this user complete the task?
- What actions did they take?
- What did they perceive?
- Where did frustration/confusion rise?
- What coping mechanism was selected?
- How much effort did success require?

Display:

- synchronized video;
- state timeline;
- action timeline;
- persona and ability profile;
- original/perceived screenshot toggle;
- selected coping probabilities;
- completion criteria.

### 28.5 UX Feedback mode

Primary questions:

- Where did the interface cause pain?
- Which elements contributed?
- What UX mechanism explains it?
- How many users were affected?
- What alternatives exist?
- What knowledge supports them?

Display:

- screenshot with pain overlays;
- root-cause card;
- observed vs inferred evidence;
- cohort impact;
- solution alternatives;
- grounding references/status.

### 28.6 Aggregate root-cause view

The output system also needs a cohort mode independent of the two per-step interpretations.

Suggested control:

```text
View: [ Individual user ] [ Aggregate root causes ] [ Isolated issue ]
```

Aggregate by normalized pain-point signature:

- screen/route;
- element role/identifier;
- diagnosis category;
- behavioral mechanism.

Show:

- affected users;
- affected iterations;
- average state impact;
- abandonment count;
- persona dimensions correlated with impact;
- ranked alternatives.

---

## 29. Report data model

JourneyTest's existing `RunResult` remains the base result.

Add optional:

```ts
interface UXRunAnalysis {
  behaviorSummary: BehavioralSummary;
  emotionalTrajectory: UserStatePoint[];
  painPoints: UXPainPoint[];
  eyeson: EyesonRunSummary;
  alternatives: UXAlternative[];
  grounding: GroundingSummary;
}
```

The final `run.json` becomes:

```text
RunResult
  + existing JourneyTest verdict/artifacts/timeline
  + uxAnalysis
```

Do not replace the existing verdict.

Semantic distinction:

- **Journey verdict:** did the task pass/fail/block?
- **UX analysis:** what experience occurred and what should change?

---

## 30. Final report structure

`report.md` and `dashboard.html` should contain:

### 1. Executive summary

- task outcome;
- experience quality;
- strongest pain point;
- strongest recommendation;
- completion/abandonment.

### 2. Synthetic user

- persona;
- behavior profile;
- abilities;
- scenario/context;
- generation/version metadata.

### 3. Journey outcome

- duration;
- actions;
- errors;
- retries;
- backtracks;
- effort;
- task result.

### 4. Experience trajectory

Charts/timeline for:

- frustration;
- confusion;
- trust;
- fatigue;
- effort.

### 5. Critical pain points

For each:

- screenshot;
- highlighted element(s);
- video timestamp;
- observed evidence;
- behavioral effect;
- diagnosis;
- persona interaction;
- grounding status/references;
- alternatives.

### 6. Eyeson UX review

- hierarchy;
- feedback;
- interaction;
- copy;
- accessibility;
- responsive/layout findings.

### 7. Alternative solutions

Rank by:

- expected impact;
- implementation effort;
- confidence;
- personas affected.

### 8. UX knowledge basis

Show provider status and retrieved sources if configured.

### 9. Full evidence

- event timeline;
- screenshots;
- perceived screenshots;
- DOM/a11y snapshots;
- UI changes;
- network/console where collected;
- video.

---

## 31. Report evidence language

Every recommendation must distinguish:

### Observed

Facts from browser and behavior engine.

### Inferred

Model diagnosis with confidence.

### Grounded

Retrieved UX guidance/research.

### Proposed

Alternative design recommendation.

This separation must be visible in the UI and serialized in `run.json`.

---

## 32. Artifact layout

Suggested per-run filesystem layout:

```text
runs/<runId>/
  run.json
  report.md
  dashboard.html
  video.webm

  persona/
    persona.json
    behavior-profile.json
    abilities.json

  events/
    events.ndjson
    behavior-events.ndjson

  screenshots/
    0001.png
    0002.png

  perceived-screenshots/
    0001.png
    0002.png

  snapshots/
    0001.txt
    0002.txt

  element-maps/
    0001.json

  ui-changes/
    0001.json

  eyeson/
    step-0001.json
    step-0002.json
    pain-points.json

  alternatives/
    <painPointId>/
      alternative-1.json
      alternative-1.png

  grounding/
    <painPointId>.json
```

Every artifact must have an index entry in `run.json`; paths alone are not sufficient.

---

## 33. Eyeson analysis scheduling

### 33.1 Screen budget

`Number of screens` means maximum distinct screen states selected for deep Eyeson analysis, not necessarily maximum browser actions.

Selection priority:

1. frustration spikes;
2. explicit errors;
3. abandonment point;
4. major route/screen changes;
5. user-selected bookmarks;
6. representative normal states.

JourneyTest may still capture more screenshots for evidence.

### 33.2 Analysis queue

Define:

```ts
interface AnalysisQueue {
  enqueue(job: EyesonAnalysisJob): Promise<void>;
  flush(runId: string): Promise<void>;
}
```

MVP: in-memory queue with concurrency limit.

Production option: BullMQ/Redis adapter.

At report finalization, either:

- wait for required analysis jobs; or
- mark report `analysisStatus = partial` and update once complete.

For a deterministic CLI/report artifact, prefer waiting for the selected screen budget to finish before final report generation.

---

## 34. Alternative retest roadmap

The data model should support a later closed loop:

```text
Original UI
 -> personas run
 -> pain point
 -> Eyeson alternative
 -> alternative prototype
 -> rerun same personas and seeds
 -> compare behavior
```

Store alternative lineage:

```ts
interface AlternativeExperimentLink {
  sourceRunId: string;
  painPointId: string;
  alternativeId: string;
  validationRunIds: string[];
}
```

Do not claim expected impact is validated until an actual rerun or real-user study supports it.

---

## 35. Observability and Langfuse

Langfuse is optional but recommended for semantic-model tracing.

Trace explicit structured steps:

- persona compilation;
- event appraisal;
- visual judgment;
- diagnosis;
- alternative generation;
- RAG retrieval.

Log:

- inputs;
- outputs;
- model/version;
- latency;
- cost where available;
- confidence;
- run/user/step correlation IDs.

Do not depend on hidden chain-of-thought. Use explicit fields such as:

- `observation`;
- `decision_rationale`;
- `diagnosis.mechanism`;
- `copingDecision`;
- `confidence`.

---

## 36. Security and browser safety

The system executes against live websites. Required safeguards:

- allowlist/denylist origins;
- restrict navigation to configured target origins by default;
- block local/private network ranges unless explicitly enabled;
- prevent arbitrary file downloads by default;
- prevent destructive actions where detectable;
- require explicit configuration for purchases, submissions or irreversible operations;
- sanitize webpage content before passing to LLMs;
- treat webpage text as untrusted data;
- never allow page content to overwrite system rules;
- redact secrets from artifacts/logs;
- isolate browser sessions per run;
- configurable cookie/auth storage policy.

---

## 37. Privacy

Synthetic persona data should not require real PII.

If authenticated test accounts are used:

- never serialize passwords into run artifacts;
- store credentials through secrets/config provider;
- mask sensitive form values in reports;
- support artifact retention policies;
- support local-only runs.

---

## 38. Reproducibility

Persist:

- experiment config hash;
- JourneyTest commit/version;
- Eyeson commit/version;
- TinyTroupe commit/version;
- DSPy version;
- LLM provider/model/version where available;
- persona seed;
- behavior seed;
- physical-simulation seed;
- temperature/config;
- state reducer version;
- coping policy version;
- UX classifier version;
- RAG provider/index version.

### 38.1 Deterministic replay mode

Provide an advanced option:

`Replay from evidence without browser`

This re-runs:

- state reducer;
- Eyeson diagnosis;
- report rendering;

against stored evidence without revisiting the website.

---

## 39. Testing strategy

### 39.1 JourneyTest behavior unit tests

Test pure functions:

- state reducer;
- wait tolerance;
- repeated failure escalation;
- anger recovery;
- coping score calculation;
- seeded sampling;
- abandonment thresholds;
- working-memory filtering;
- physical pointer noise.

### 39.2 Contract tests

Validate JSON contracts between:

- Eyeson backend and JourneyTest;
- JourneyTest and persona runtime;
- evidence coordinator and Eyeson analysis;
- report serializer and frontend.

Use JSON Schema/Zod/Pydantic generated from shared definitions where practical.

### 39.3 Browser integration fixtures

Create deterministic local fixture websites for:

- delayed button response;
- explicit error;
- ambiguous error;
- small click target;
- color-only status;
- repeated validation failure;
- disappearing toast;
- slow loading with progress;
- slow loading without progress;
- successful recovery;
- abandonment path.

### 39.4 Visual regression

Snapshot-test:

- pain overlays;
- original/perceived mode;
- report mode switch;
- alternatives view.

### 39.5 DSPy evaluation

Create labeled datasets for:

- persona -> behavior mapping;
- event classification;
- element pain attribution;
- UX classification;
- alternative quality.

Later optimize DSPy programs against real human-study examples.

---

## 40. Calibration roadmap

Do not treat initial coefficients as human-truth estimates.

Collect real-study measures:

- completion;
- time;
- action sequence;
- misclicks;
- retries;
- backtracks;
- help usage;
- abandonment;
- self-reported frustration;
- observed confusion;
- discovered UX issues.

Compare synthetic and real cohorts.

Potential optimization metric:

```text
0.30 action-sequence agreement
0.20 completion agreement
0.20 UX issue agreement
0.15 abandonment agreement
0.15 frustration calibration
```

Exact weights require research validation.

---

## 41. Current-code migration plan

### Phase 0 — dependency baselines

- Fork/pin JourneyTest-core.
- Pin Eyeson main commit.
- Add TinyTroupe and DSPy lockfile.
- Add `persona-runtime` Docker service.
- Add shared run ID and artifact IDs across services.

**Acceptance:** existing JourneyTest and Eyeson tests still pass independently.

### Phase 1 — one JourneyTest run inside Eyeson

Implement Eyeson backend adapter that calls JourneyTest library API.

Output:

- live run events;
- `video.webm`;
- screenshots;
- existing JourneyTest report.

**Acceptance:** a URL/task can be started from Eyeson UI and visually replayed.

### Phase 2 — TinyTroupe persona generation

- generate persona in Python;
- serialize to Eyeson;
- attach to JourneyTest profile;
- display persona in live/report UI.

**Acceptance:** multiple generated users produce persisted distinct profiles.

### Phase 3 — BehaviorController MVP

Implement:

- patience;
- persistence;
- frustration;
- trust;
- repeat failure;
- wait tolerance;
- retry;
- reread;
- abandon.

**Acceptance:** fixture app produces seed-reproducible different coping behavior for different profiles.

### Phase 4 — DSPy persona compiler

Convert TinyPerson to structured BehaviorProfile.

**Acceptance:** compiled profile validates against schema and is stored once per user.

### Phase 5 — evidence bus and screenshot streaming to Eyeson

Every selected screenshot is queued for Eyeson analysis with its exact element map and behavior transition.

**Acceptance:** Eyeson findings appear on the same step/timestamp as JourneyTest evidence.

### Phase 6 — pain-point resolver

Implement:

- pain episodes;
- element attribution;
- behavioral impact;
- screenshot overlays.

**Acceptance:** fixture errors highlight the correct element(s) with traceable evidence.

### Phase 7 — two-mode report UI

Implement:

- User Journey mode;
- UX Feedback mode;
- mode-switch preserving timestamp/step;
- original/perceived screenshot toggle.

**Acceptance:** switching modes never changes selected run/user/step.

### Phase 8 — alternative generation

- structured alternatives;
- impact/effort/confidence;
- optional visual render provider.

**Acceptance:** every major pain point has zero or more alternatives tied explicitly to that pain point; no generic unattached recommendations.

### Phase 9 — RAG placeholder

Ship `UXKnowledgeProvider`, `NullUXKnowledgeProvider`, grounding schema and UI state.

**Acceptance:** report cleanly shows `not_configured` without errors.

### Phase 10 — physical/perceptual profiles

Implement incrementally:

- color vision transform;
- contrast/acuity transform;
- reading speed;
- working-memory filtering;
- motor pointer simulation.

**Acceptance:** original and perceived artifacts are both preserved and effects are reproducible by seed/profile.

### Phase 11 — cohort aggregation

- user/iteration aggregation;
- root-cause clustering;
- persona susceptibility analysis;
- suite dashboard extensions.

**Acceptance:** users can move between individual, aggregate root-cause and isolated-issue views.

### Phase 12 — knowledge grounding implementation

Populate the provider with curated UX sources and/or internal research.

**Acceptance:** recommendations show source identity and clearly distinguish observed/inferred/grounded/proposed claims.

---

## 42. Recommended Eyeson file additions

Under `ux-analyst-ai/backend/`:

```text
integrations/
  journeytestAdapter.js
  personaRuntimeClient.js

services/
  experimentOrchestrator.js
  evidenceCoordinator.js
  eyesonEvidenceAnalyzer.js
  painEpisodeAggregator.js
  painPointResolver.js
  alternativeGenerator.js
  alternativeRenderer.js
  reportEnricher.js

knowledge/
  UXKnowledgeProvider.js
  NullUXKnowledgeProvider.js

queues/
  AnalysisQueue.js
  InMemoryAnalysisQueue.js

models/ or core/
  experimentSchemas.js
  evidenceSchemas.js
  uxAnalysisSchemas.js

routes/
  experiments.js
  runs.js
  painPoints.js
```

The exact folder names may be adapted to Eyeson's existing conventions, but responsibilities should remain separated.

---

## 43. Recommended frontend components

Under Eyeson's existing frontend:

```text
ExperimentBuilder/
  TargetTaskSection
  PersonaSection
  AbilitySection
  BehaviorSection
  AnalysisSection
  ExecutionSection

RunLiveView/
  PersonaCard
  BrowserReplay
  StateMeters
  CopingCard
  LiveTimeline
  AnalysisStatus

RunReport/
  ModeSwitcher
  EvidenceViewer
  JourneyTimeline
  StateTimeline
  PainOverlay
  PainPointPanel
  RootCausePanel
  AlternativePanel
  KnowledgePanel
  CohortSummary
```

### 43.1 EvidenceViewer modes

Journey mode overlays:

- original;
- persona perceived;
- interaction targets.

UX mode overlays:

- frustration;
- confusion;
- repeated action;
- missed elements;
- accessibility;
- Eyeson findings.

---

## 44. Shared schema package

Strongly recommended: create one versioned schema package in the Eyeson host repo.

```text
ux-analyst-ai/shared-schema/
```

Source of truth can be JSON Schema or TypeScript/Zod with generated Pydantic equivalents.

Core shared objects:

- `ExperimentConfig`;
- `SyntheticUserProfile`;
- `BehaviorProfile`;
- `FunctionalAbilitySpec`;
- `UserState`;
- `ExperienceEvent`;
- `CopingDecision`;
- `JourneyStepEvidence`;
- `UXPainPoint`;
- `UXDiagnosis`;
- `UXAlternative`;
- `UXKnowledgeResult`;
- `UXRunAnalysis`.

Schema version must be present in all cross-process payloads.

---

## 45. Failure handling

### Persona runtime unavailable

- fail persona generation cleanly before starting browser; or
- use configured fallback manual profile.

### DSPy appraisal unavailable

- use native classifier result with lower confidence;
- mark semantic appraisal `unavailable`.

### Eyeson deep analysis fails

- journey continues;
- report marks affected step analysis as failed;
- JourneyTest evidence remains usable.

### RAG unavailable

- alternatives can still be generated from diagnosis;
- grounding status remains `not_configured` or `failed`.

### Visual solution provider unavailable

- keep textual/structured alternative;
- do not fail the report.

---

## 46. Performance requirements

Suggested first targets:

- state/coping computation: < 20 ms per event excluding LLM calls;
- no deep Eyeson critique in the critical action path;
- persona compiler: one call/user;
- deep analysis limited by screen budget;
- dashboard usable with 500+ timeline events through virtualization or incremental rendering;
- artifacts streamed/written rather than held entirely in memory.

---

## 47. Product semantics and wording

Do not market simulated outcomes as equivalent to human study results.

Use wording such as:

- "synthetic-user simulation";
- "simulated frustration signal";
- "model-estimated impact";
- "likely UX mechanism";
- "grounded recommendation" only when a knowledge source is actually attached.

Avoid:

- "users will be 31% less frustrated" unless backed by empirical validation;
- "elderly users cannot...";
- medical claims from demographic profile fields.

---

## 48. Definition of a complete v1

The application is considered functionally complete when a user can:

1. Open Eyeson frontend.
2. Enter a URL and task.
3. Configure synthetic users/iterations and scenario.
4. Start the experiment.
5. Have TinyTroupe generate personas.
6. Have DSPy compile behavior profiles.
7. Watch JourneyTest execute at least one live journey.
8. See dynamic state and coping decisions update.
9. Replay the generated video.
10. Inspect original screenshots and persona-perceived screenshots where configured.
11. Have the same screenshots automatically analyzed by Eyeson.
12. See pain points tied to one or more interface elements.
13. Switch between `User Journey` and `UX Feedback` without losing selected timestamp/step.
14. View a structured UX diagnosis containing observed evidence, behavioral impact and inference confidence.
15. View alternative solutions tied to the diagnosed pain point.
16. See the RAG grounding area, even if it says `not configured`.
17. Export/open `run.json`, `report.md`, `dashboard.html`, screenshots and video.
18. Run multiple users/iterations and inspect aggregate root causes.

---

## 49. Primary architectural decisions

### Decision A — Eyeson is the host app

**Chosen because:** it already contains backend, frontend, CLI and deployment structure.

### Decision B — JourneyTest is the only live browser owner

**Chosen because:** it already has the strongest closed-loop browser/evidence design and avoids state drift between separate browsers.

### Decision C — TinyTroupe defines identity, not browser mechanics

**Chosen because:** persona consistency is its strength; deterministic physical/behavioral simulation is better implemented in explicit code.

### Decision D — DSPy is used selectively

**Chosen because:** semantic transformations benefit from typed LLM programs and later optimization, while state/timers/physical effects require deterministic code.

### Decision E — behavior state is authoritative in TypeScript/JourneyTest

**Chosen because:** action policy and browser effects must remain reproducible and available even if the Python semantic service is unavailable.

### Decision F — Eyeson consumes JourneyTest evidence

**Chosen because:** the UX critique must discuss the exact state the user actually experienced.

### Decision G — RAG is a provider interface in v1

**Chosen because:** report and diagnosis schemas should not need redesign when knowledge grounding is added later.

### Decision H — AI-UX is not in the critical runtime path

**Chosen because:** its precomputed prototype simulation is conceptually different from live closed-loop user testing. Reuse only rendering/prototyping ideas where valuable.

---

## 50. Key end-to-end sequence

```text
1. User configures experiment in Eyeson.

2. Eyeson orchestrator creates synthetic-user requests.

3. Persona runtime:
   TinyTroupe -> PersonaSpec
   DSPy -> BehaviorProfile
   explicit config -> FunctionalAbilitySpec

4. Eyeson starts JourneyTest run with:
   task
   profile
   behavior
   abilities
   seed

5. JourneyTest opens the website.

6. JourneyTest captures semantic + visual evidence.

7. If needed:
   screenshot -> perception transform -> DSPy persona visual judgment.

8. JourneyTest agent selects intention/action.

9. BehaviorController modifies execution if necessary:
   hesitation
   reading delay
   pointer noise
   etc.

10. Browser executes action.

11. JourneyTest observes UI changes.

12. ExperienceClassifier creates event.
    If ambiguous -> DSPy appraisal.

13. StateReducer updates:
    frustration
    confusion
    trust
    effort
    fatigue

14. CopingPolicy produces probability distribution and selects coping intent.

15. EvidenceCoordinator saves step and emits live event.

16. Screenshot + semantic evidence is sent to Eyeson deep analysis queue.

17. Journey continues without waiting for deep analysis.

18. Eyeson returns findings and element attribution.

19. At run end:
    JourneyTest creates verdict.
    Eyeson aggregates pain episodes.
    PainPointResolver creates UXPainPoints.
    UXKnowledgeProvider optionally retrieves grounding.
    AlternativeGenerator creates solutions.

20. ReportEnricher adds UXRunAnalysis to RunResult.

21. Render:
    run.json
    report.md
    dashboard.html
    video.webm

22. Frontend displays synchronized modes:
    User Journey <-> UX Feedback.
```

---

## 51. Future roadmap

### Persona pool (GitHub Actions)

Replace live per-request TinyTroupe generation as the default path with a
pre-generated, continuously-refreshed pool: a dedicated GitHub repository of
personas, kept diverse and current by a scheduled GitHub Actions workflow
(daily), with in-app lookup that finds the closest-ranged group of pool
personas for a given theme/customer-profile/trait request instead of
generating fresh ones synchronously. Full plan, phases, and open questions:
[`docs/persona-pool-plan.md`](persona-pool-plan.md).

### RAG/knowledge

- curated WCAG/WAI corpus;
- usability heuristics;
- design-system guidance;
- peer-reviewed UX/HCI literature;
- internal design system;
- previous usability studies;
- support tickets;
- analytics findings;
- A/B test results.

### Empirical calibration

- real-user/synthetic-user paired studies;
- DSPy optimization;
- behavior coefficient fitting;
- persona cohort calibration.

### Design iteration

- automatically retest generated alternatives;
- compare original vs alternative behavior;
- rank alternatives by simulated cohort impact.

### Additional modes

- accessibility audit;
- cognitive walkthrough;
- first-click testing;
- responsive comparison;
- design-version regression;
- aggregate cohort segmentation.

### AI-UX integration option

Use AI-UX only if a future Figma/prototype rendering workflow becomes valuable. Keep it behind `VisualSolutionProvider` or `PrototypeExportProvider`.

---

## 52. Implementation priority summary

If engineering starts immediately, build in this order:

1. Eyeson -> JourneyTest library integration.
2. Shared run/evidence IDs.
3. TinyTroupe persona runtime.
4. BehaviorProfile + BehaviorController MVP.
5. Live state/coping events.
6. Screenshot/evidence streaming to Eyeson.
7. Pain-point aggregation and element attribution.
8. Two-mode report UI.
9. Alternative generation.
10. RAG provider placeholder.
11. Physical/perceptual simulation.
12. Cohort/root-cause aggregation.
13. Actual RAG grounding.
14. Empirical calibration and alternative retesting.

This order delivers a useful application early while preserving the architecture needed for the full research vision.
