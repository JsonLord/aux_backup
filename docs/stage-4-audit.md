# Stage 4 — persona compiler audit

Date: 2026-08-26

## Implemented

- `BehaviorProfile` is now an explicit Pydantic contract. It requires the complete
  Stage 4 trait set plus the behavior seed, rejects unknown fields, rejects missing
  fields, and constrains normalized traits to `0..1`.
- The semantic compiler normalizes both the direct/mock baseline and explicitly
  selected DSPy predictions through the same schema. Non-finite outputs fail instead
  of entering persisted profiles.
- Compiler implementation and provider versions are recorded in generation metadata.
- Generation invokes the compiler once for each new synthetic user. The validated
  result is embedded in the durable profile and subsequently transferred by artifact
  reference rather than recomputed for each browser step.
- The DSPy signature covers every `BehaviorProfile` semantic trait. DSPy remains an
  explicit opt-in and does not introduce a second browser agent.

## Acceptance evidence

Contract tests validate the exact output schema, normalized values, extra-field
rejection, compiler provenance, one compilation call per generated user, and durable
round-trip of the compiled profile without recompilation.

## Gate retained

DSPy 3.3.0 remains gated behind the human-reviewed direct-versus-DSPy parity report.
The deterministic mock remains the CI/offline engine, and the direct Blablador
compiler remains the credentialed baseline. Stage 4 establishes and validates the
DSPy compiler boundary; it does not make DSPy the default before parity approval.

## Update: persona-varied ability compilation + live DSPy wiring (2026-08-28)

Extends the same compiler boundary to spec.md §6.1's "Functional abilities"
category (vision, motor, cognition, reading), which was previously a static,
identical-for-every-persona default (`default_abilities()`), not a compiled
per-persona output:

- `AbilityProfile` (`models.py`) is now an explicit, typed contract, mirroring
  `BehaviorProfile` but with `extra="ignore"` and field defaults (not
  `extra="forbid"`) since this nested structure is also built up incrementally by
  manual UI edits (`apply_persona_tweaks`) that do not touch every field.
- `PersonaCompiler.compile_abilities_with_metadata` mirrors
  `compile_with_metadata` exactly, under the identical `PERSONA_COMPILER` gate
  (native semantic engine by default; `dspy` opt-in, same as behavior). Both the
  mock and direct semantic engines implement `compile_abilities`; the DSPy
  signature is `CompileAbilityProfile` in `dspy_program.py`.
- Ability sampling is explicitly instructed, in every engine, to never infer,
  correlate, or condition any value on the persona's age, gender, occupation, or
  other demographic/biographical detail (same principle as the existing behavior
  compiler's "never infer impairments from demographics"). The deterministic mock
  engine enforces this structurally: its RNG draws never branch on any persona
  field, only on a seed derived from the whole persona (for reproducibility) --
  verified by a statistical test asserting no age-correlated drift in mean acuity
  across many samples.
- `default_abilities()` is retained, narrowed to its actual remaining use: the
  fully-offline fallback path when persona generation itself already failed and no
  compiler call is being made at all.
- `generator.py`'s `_profile()` now runs the behavior and ability compilation calls
  **concurrently** (`ThreadPoolExecutor(max_workers=2)`) rather than adding a
  second sequential call per persona, since the two are independent given the same
  persona/scenario/seed.
- DSPy 3.3.0 is now installed on the live image (`spaces/aux-live/requirements-live.txt`,
  full dependency resolution -- not `--no-deps` like TinyTroupe, since DSPy's
  litellm-based LM backend needs its real transitive dependencies to function, not
  just import) and `dspy_program.configure_lm()` points DSPy's global LM at the
  same `OPENAI_*` settings the rest of the service already uses (via litellm's
  `openai/<model>` custom-`api_base` convention). Verified end-to-end against the
  live provider (both `CompileBehaviorProfile` and `CompileAbilityProfile`,
  through the actual `PersonaCompiler` code path, not just a raw `dspy.Predict`
  call) before this was deployed.
- **The gate above is unchanged by this update.** `PERSONA_COMPILER` still
  defaults to `native`; DSPy is now genuinely selectable (`dspyAvailable: true`,
  and functionally verified) but is not switched on as the Space default. The
  parity report this section's gate refers to has not been extended to cover the
  new ability signature; that remains open if/when DSPy activation is revisited.
