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
