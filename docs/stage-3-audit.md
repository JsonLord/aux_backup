# Stage 3 — BehaviorController MVP audit

Date: 2026-08-26

## Implemented

- The Journey worker owns deterministic dynamic user state and updates it through a
  pure reducer after normalized experience events.
- Failure impact accounts for severity, goal blockage, emotional momentum, and a
  nonlinear repeated-event multiplier. Success, recovery, and progress events reduce
  frustration, anger, and confusion according to the profile's recovery trait.
- Waiting tolerance is computed from patience, frustration, trust, visible progress,
  task importance, time pressure, and expected complexity. Each transition exposes
  the threshold, inputs, and coefficient version for evidence and debugging.
- Coping scores cover retry, reread, wait, explore, seek help, backtrack, impulsive
  retry, and abandon. Scores are converted to probabilities and sampled by a seeded
  PRNG; both the selected structured intent and full distribution are persisted.
- `/v1/runs` accepts optional normalized `experienceEvents` for deterministic fixture
  and replay execution while preserving the default fixture observation path.

The reducer, wait tolerance, and coping-policy constants are explicitly versioned
simulation coefficients. They are not presented as calibrated estimates of human
behavior.

## Acceptance evidence

The Node test suite verifies deterministic replay, nonlinear repeated-failure
escalation, anger/frustration recovery inputs, visible-progress wait tolerance,
profile-sensitive score distributions, and seed-reproducible different decisions
(`retry` versus `impulsive_retry`) for two fixture profiles.

## Remaining integration boundary

Stage 3's native behavior MVP is complete. Browser realization of coping intentions
and classification of live browser observations remain a `PLACEHOLDER` until the
pinned JourneyTest library path replaces the fixture adapter. The behavior layer does
not import or call Eyeson, the persona service, or the control plane; it consumes the
versioned run payload and emits serializable transition evidence.
