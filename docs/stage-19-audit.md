# Continuation Stage 19 — browser safety audit

Date: 2026-08-26

The Journey boundary now accepts only absolute HTTP(S) targets, blocks loopback,
link-local, and private IP networks by default, applies origin allow/deny policy, and
requires explicit permission for detectable irreversible tasks. Downloads default to
disabled, cookies default to ephemeral, and each run declares isolated-session policy.

Helpers redact credential-shaped fields and wrap bounded webpage text as untrusted
content before semantic use. Live browser middleware enforcement remains inside the
pinned JourneyTest adapter and must honor the validated policy returned by the native
boundary.
