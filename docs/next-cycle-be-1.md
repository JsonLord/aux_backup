# BE-1: route runs through the workspace's providers

Build plan. Written 2026-09-19 against the tree at `26ed598` — after BE-2, which
moved two of the affected call sites into `services/report_service/`. Every line
reference below was checked against that tree.

Scheduled in `docs/next-cycle-plan.md` (BE-1); the shorter sketch in
`docs/next-cycle-tracks-b-c.md` is superseded by this document, which found two
things that sketch did not: the work spans **four** processes, not two, and the
admission decision **cannot be re-derived at run time**.

## What is already there

Three pieces that fit, and one missing wire.

`ModelSettingsStore.chain(workspace_id, role)` (`model_settings.py:211`) returns
`list[tuple[base_url, api_key, model]]`, ordered by `position`, skipping rows whose
Space secret has left the environment. Roles are `generation`, `acting`,
`reflection`, `vision` (`model_settings.py:48-52`).

`model_providers()` (`providers.py:42`) returns **the same tuple shape** from the
environment — the deployment default — deliberately, "so a configured workspace and
a default one are walked by the same code".

`DirectLLMSemanticEngine._chain()` (`semantic.py:233`) is where a Python model call
decides what to try, and `_complete()` (`semantic.py:176`) walks it with the retry
discipline already correct: `unreachable()` (`providers.py:108`) separates *no model
saw the question* (DNS, reset, 502/503/504 → try the next provider) from *a model
answered unhappily* (400, 401 → the next one reaches the same verdict, so stop).

## The gap

`chain()` has exactly one non-test caller in the tree — `app.py:2805` — and it is an
**admission gate**, not a routing decision:

```python
if _model_settings_store().chain(auth.get("workspace_id") or workspace_id or "local", "acting"):
    return                      # allowed to run; nothing says what it runs on
```

Every actual model call still resolves from the environment. So a workspace
configures its own provider, is admitted on the strength of having done so, and the
run then spends **the deployment's** built-in credentials — the outcome
`model_settings.py`'s own opening docstring says the module exists to prevent.

## Four processes, not two

| Process | Where it resolves a model today | Already injectable? |
| --- | --- | --- |
| Control plane (in-process) | `DirectLLMSemanticEngine()` at `executor.py:563` and `assembler.py:2508`, both gated on `os.getenv("OPENAI_API_KEY")` (`executor.py:559`, `assembler.py:2504`) | constructor takes `base_url`/`model`/`api_key` |
| `persona_service` (:8090) | `semantic_engine()` at `compiler.py:111` and `:132` | same constructor |
| `journey-worker` (Node) | `journeytest.js:279-288` reads `OPENAI_API_KEY`/`OPENAI_BASE_URL` and the `JOURNEY_REFLECT_*` trio | **yes** — `llmActor()` (`personaActor.js:515`) already takes acting, reflection and fallback endpoints as arguments |
| `eyeson-worker` (Node) | `visionCritique.js:526-528` | **yes** — `critique({model, apiKey, baseUrl, …})` (`visionCritique.js:440`) already takes them as options |

Both Node workers already accept injection; only the wiring above them reads the
environment. That is most of BE-1's luck.

## Decision 1 — the control plane resolves; workers receive

`persona_service`, the journey worker and the eyeson worker are separate processes.
Two of them could open the control-plane SQLite file in the single-container Space
deployment, and must not: `AGENTS.md` says services "communicate only through
versioned HTTP contracts, job IDs, and persisted artifact references".

So one rule, the same in all three directions: **the control plane resolves the chain
and puts it in the request; a worker uses what it is given, and falls back to its own
environment only when it is given nothing** — which keeps a worker started by hand,
or by its own tests, working unchanged.

## Decision 2 — admission is decided at job creation, not at run time

This is the finding that changes the shape of the work.

`may_use_built_in_providers(auth)` (`model_settings.py:91`) needs an **auth dict**: it
reads `auth["role"]`, and `_identifiers()` reads `owner_user_id`, `user.username`,
`user.id`, `user.name`. The executor does not have one. It has a **job**, and a job
carries only `workspace_id` and `owner_user_id` (`store.py:53`).

That is not enough, and quietly so. In `hf_token` mode `owner_user_id` is the HF
`sub` — a subject id — while `space_owner()` yields a **username** from `SPACE_ID` or
`SPACE_AUTHOR_NAME` (`auth.py:121` sets `user.username` from `preferred_username`
separately). Re-deriving the decision from the job would therefore deny the Space's
own owner the credentials reserved for them, on every asynchronous run, with no error
anyone would read as being about identity.

`create_job` has the full auth dict (`main.py:125`, `auth=Depends(identity)`). So:

> Decide it once, where `auth` exists, and record it on the job.

Stamp `metadata.modelAccess = {"builtInAllowed": bool, "decidedFor": <identifier>}`
at creation; the executor reads the boolean. Two further reasons this is the right
shape rather than a workaround: the decision becomes **auditable** — a run records
whose budget it was allowed to spend — and it cannot **drift**, so editing
`AUX_DEFAULT_PROVIDER_OWNERS` mid-run does not change what a running job may do.

The bundled-example allowance (`example_persona=`) is decided in the same place, from
the job's input artifacts.

## Decision 3 — ordering, and what "fallback" means for a stranger

```
1. explicit constructor arguments        (tests, and callers that pin an endpoint)
2. this workspace's own providers        ModelSettingsStore.chain(workspace_id, role)
3. the deployment's built-in providers   model_providers()  -- ONLY if builtInAllowed
```

Step 3 is conditional, and that is the entire point. Appending the built-in providers
unconditionally would make the admission gate decorative: refused at the door, served
at the back. For a caller who may not spend them, the deployment default is not a
fallback — it is not in the list at all, and a run with an empty chain fails with
`why_not_built_in()` (`model_settings.py:101`), which already writes the message.

## The work

**Status: BE-1a, BE-1b and BE-1d have landed.** The engine takes a resolved chain, the
control plane composes one per job and role, and the decision about the built-in
providers is recorded at job creation. Twelve tests cover it. A journey now runs on the workspace's own
providers when it has them. BE-1c (persona_service), BE-1e (eyeson worker) and
BE-1f (record which provider served) remain, so persona compilation and the
vision critique still resolve from the environment.

Two things came out different from this plan and are recorded under **What actually
changed** at the end.


### BE-1a — the engine learns who it works for — **done**

```python
class DirectLLMSemanticEngine:
    def __init__(self, api_key=None, base_url=None, model=None,
                 *, workspace_id: str | None = None, role: str = ROLE_GENERATION,
                 built_in_allowed: bool = True): ...

    def _chain(self) -> list[dict]:
        chain = [ ... ]                                   # explicit, as today
        if self.workspace_id:
            for url, key, model in _settings_store().chain(self.workspace_id, self.role):
                chain.append({"base_url": url, "api_key": key, "model": model})
        if self.built_in_allowed:
            for url, key, model in model_providers():
                chain.append({"base_url": url, "api_key": key, "model": model})
        return _deduplicated(chain)                       # on (base_url, model), as today
```

`built_in_allowed` defaults to `True` so every existing caller and test behaves
exactly as before until it is threaded. `_settings_store()` is a module-level lazy
singleton, so `semantic.py` takes no import-time dependency on the control plane.

`__init__` currently raises `ValueError` when no key resolves (`semantic.py:121`).
With a workspace chain that check moves to "is there anything in the chain at all",
because a workspace provider supplies its key from the store rather than the
environment.

### BE-1b — thread it through the two control-plane call sites — **done**

Both are reached from `_combined_test(self, job)`, which has the job:

- `_attach_redesigns(cls, findings, url)` (`assembler.py:2468`, called at
  `executor.py:336`) → `_generate_redesign_fragment` (`assembler.py:2498`), role
  **vision**.
- `_ui_adaptation(self, job)` (`executor.py:541`) → `_generate_ui_html`
  (`executor.py:553`), role **vision**.

Each gains `workspace_id` and `built_in_allowed` parameters. The
`if not (os.getenv("OPENAI_API_KEY") or os.getenv("BLABLADOR_API_KEY")): return None`
guards (`executor.py:559`, `assembler.py:2504`) become "is this workspace's chain for
this role empty" — the same question asked correctly, and it stops a configured
workspace being told no model is available because the *deployment's* keys are absent.

### BE-1c — persona_service over HTTP

`/v1/personas/compile` and `/v1/personas/generate` take an optional `models` block;
absent, `semantic_engine()` (`compiler.py:111`, `:132`) behaves exactly as today.
Role **generation**. The caller (`apps/gradio/api_client.py`) resolves and sends it.

### BE-1d — the journey worker — **done**

The executor already builds the `/v1/runs` payload and already passes
`sessionStatePath` and `identity` through it. Add:

```jsonc
"models": {
  "acting":     [{"baseUrl": "...", "model": "...", "apiKey": "..."}],
  "reflection": [{"baseUrl": "...", "model": "...", "apiKey": "..."}]
}
```

`journeytest.js:279-288` prefers it over the environment and hands it to `llmActor()`
(`personaActor.js:515`), which already accepts acting, reflection and a fallback
triple — so a two-entry chain maps on with no change to the actor itself. A chain
longer than two needs `llmActor` to take a list; do that when a workspace actually
configures three, not before.

### BE-1e — the eyeson worker

Same shape, role **vision**: the request carries the chain,
`visionCritique.js:526-528` prefers it over the environment, and `critique()`
(`visionCritique.js:440`) already takes `{model, apiKey, baseUrl}`.

### BE-1f — record which provider served

`_complete()` already knows which entry answered. Record its **host and model, never
the key** on the run, and print it in the report: a run served by the fallback is a
run whose reproducibility claim differs. This is also the hook BE-3 hangs token and
wall-time accounting on.

## Keys travel in request bodies

Three of the five steps put a decrypted API key into an HTTP body. That is the same
trust boundary `CredentialStore.capture_session()` already crosses — it posts a
decrypted session over loopback — and it is acceptable for the same reason. What it
requires, and what must be built rather than assumed:

- **Nothing logs the payload.** `redactSensitive()` (`safety.js:34`) already matches
  `api[-_]?key` and `authorization`; the journey worker's run recorder must be made
  to pass the request through it before anything is written to the timeline.
- **Nothing echoes it in an error.** A failed `/v1/runs` currently reports the
  response body; the request must never join it.
- **Loopback or in-cluster only.** A worker URL pointing off-host would post a
  customer's key across the network. `privateHost()` (`safety.js:7`) knows the
  ranges; the check belongs at the point the worker URL is read.

## Tests, each proving the rail rather than the happy path

1. A workspace's own providers are tried **before** the deployment's.
2. A caller with `builtInAllowed: false` gets a chain that **does not contain** the
   built-in providers, even with `OPENAI_API_KEY` set in the environment. *(This is
   the rail. The happy path passes either way, which is exactly why it needs its own
   test.)*
3. With `builtInAllowed: false` and no configured provider, the run fails with
   `why_not_built_in()` rather than silently succeeding on the deployment's key.
4. A 503 from the first entry advances to the second; a 401 does not.
5. A workspace with a configured provider and an **empty environment** completes a
   call end to end.
6. The admission decision recorded at job creation is the one the executor uses —
   changing `AUX_DEFAULT_PROVIDER_OWNERS` after creation does not change the run.
7. The Space owner, identified by username, is still allowed — the regression
   Decision 2 exists to prevent.
8. Whatever the run recorder writes for a `/v1/runs` dispatch contains no key.

## What BE-1 does not do

- **It does not add a UI.** Configuring a provider stays the existing dialog
  (`apps/gradio/model_settings_panel.py`) until CAP-1.
- **It does not add roles.** The four in `model_settings.py:48-52` are what get wired.
- **It does not change the retry discipline.** `unreachable()` is already right.
- **It does not make workers read the store.** Decision 1.
- **It does not touch `app.py:2805`.** That admission gate stays; BE-1 gives its
  verdict somewhere to be recorded and used.

## Done when

A run in a workspace that has configured its own provider, with **no
`OPENAI_API_KEY` in the environment**, completes end to end — persona compile,
journey, vision critique and re-design — and the report names the provider that
served it. And a caller who may not spend the built-in credentials cannot cause a
single call to be made on them.

## What actually changed, where it differs from the plan above

**The engine does not read the settings store.** The plan's BE-1a sketch had
`DirectLLMSemanticEngine` take `workspace_id` and `role` and call the store itself.
It cannot: `semantic.py` lives in `services/persona_service/`, which runs as its own
process on :8090, and importing `apps.api.model_settings` there would make a service
reach into the control plane's database — the isolation `AGENTS.md` asks for, and the
thing Decision 1 exists to prevent one paragraph further down. The same constraint
the plan applied to the workers applies to this module.

So the engine takes `providers=` — a chain the caller already resolved — and
composition lives in a new control-plane module, `apps/api/model_routing.py`:

```python
providers_for(workspace_id, role, *, built_in_allowed)   # store chain, then built-ins if allowed
record_model_access(metadata, auth, *, example_persona)  # stamped at job creation
built_in_allowed(job)                                    # what was stamped
```

`providers=None` means "resolve from the environment as before", so every caller not
yet threaded is untouched. `providers=[]` is *not* the same thing: it means this
caller has no provider at all, and the engine raises rather than falling back onto
credentials it may not use. That distinction is what makes the rail hold.

**The example-persona allowance had to be carried onto the job.** `app.py` lets
somebody trying a bundled example through on the Space's credentials
(`_refuse_unless_provisioned`), and the job would then have recorded
`builtInAllowed: false` — the run disagreeing with the gate that admitted it, and the
demo path quietly losing its re-designs. The API workflow now puts `examplePersona`
into the job metadata and `record_model_access` reads it. The Gradio Persona Studio
path (`start_and_monitor_sessions`) does **not**, and must not: it receives
already-created personas and has no example-persona notion in scope at all. An
earlier attempt to add it there was a `NameError` the suite caught.

**A legacy job keeps what it had.** `built_in_allowed({})` is `True`. Denying the
built-ins to jobs queued before this existed would break them all on deploy, which is
a worse failure than the one being guarded against.

### What BE-1d changed beyond the plan

**A chain is sent only when it changes something.** The plan had every run carry
one. That would have been a silent regression: the worker has model settings of its
own, and the live Space sets `JOURNEY_REFLECT_MODEL=alias-fast` deliberately —
reflection is a factual comparison that happens on every step, so it runs on a
small fast model, and the code defends that choice at length. Sending the
general-purpose chain would have overwritten it with `OPENAI_MODEL` and dropped the
optimisation without a word. So `_run_models()` sends a chain when the workspace
configured providers of its own, or when the run may **not** use the deployment's,
and otherwise sends nothing and leaves the worker its own settings.

That second case matters as much as the first: omitting the block for a refused run
would send the worker back to its environment, which holds exactly the credentials
that run may not spend. A refused run is sent `{"acting": []}` — present, and empty
— and the worker refuses on it.

**The refusal moved ahead of the browser package.** `runWithJourneyTest` loaded
`journeytest-core` before anything else, so a run with no provider found that out
only after the expensive setup. A cheap refusal belongs first, and the test that
proves it cannot run at all otherwise.

**The redaction the plan asked for was already true, and is now held in place by a
test.** Nothing in the worker records the request: `runWithJourneyTest` echoes
`input.profile` into its result but never `input.models`, and `reasoningCapture`'s
`fetch` wrapper reads the *response* body only, never `init` — so the
`authorization` header it would otherwise carry never reaches a capture. The test
asserts a key put through `redactSensitive()` does not survive it.
