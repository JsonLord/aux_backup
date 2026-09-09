# Upstream Sources

## Eyeson

**Repository:**
https://github.com/JsonLord/eyeson

**Disposition:**
Imported into `services/eyeson-engine` and owned by this repository.

**Imported commit:**
`1b78aa2`

**Notes:**
This codebase is to be migrated and integrated into the aux platform. Expect architectural changes to remove independent browser capture, integrate with JourneyTest screenshots, and add element attribution, pain resolution, and alternatives.

**Update (2026-08-28):** the actual live integration did not migrate this
`services/eyeson-engine` codebase (a Node/Express/React app with a
Gemini-specific `AICritiqueService`, no configured credential in this
deployment) -- instead `services/eyeson-worker` (a lightweight from-scratch
Node worker already in this repo) gained a new `visionCritique.js` that does
what this note asked for, against the OpenAI-compatible endpoint already
configured for the whole deployment rather than a separate Gemini key:
JourneyTest screenshots feed it directly, findings carry real element
attribution (selector + boundingBox, cropped into the report) when
journeytest-core's own semantic snapshot has a matching element, and findings
are grounded through `knowledge.js`'s `CuratedUXKnowledgeProvider` (real WCAG/
Nielsen Norman references -- this existed before but was never actually
invoked). "Alternatives" is real but simpler than this repo's `alternatives.js`
template system (itself still an explicit `html-css-sandbox-placeholder`, and
gated to the unrelated native-fixture-engine pain-point path): each vision
finding's `recommendation` is a real, specific, LLM-generated suggestion, not
a category-keyed template. Verified against real target sites, including a
genuine severe bug (page content recursively repeating) that the
task-completion-only verdict had no way to catch. `services/eyeson-engine`
itself remains unmigrated reference code, not deployed.

---

## JourneyTest

**Repository:**
https://github.com/Jules-Astier/journeytest-core

**Disposition:**
External npm dependency. Do not vendor.

**Version:**
`@baguette-studios/journeytest-core@0.1.2` (exact npm pin)

**Required baseline:**
commit: `9139d581fc6a882257ea4c46bdf16d59547c0ae5`

**Fork strategy:**
If middleware hooks are required that upstream doesn't expose, fork to `JsonLord/journeytest-core` and pin:

```json
{
  "dependencies": {
    "@baguette-studios/journeytest-core": "github:JsonLord/journeytest-core#<commit-sha>"
  }
}
```

---

## TinyTroupe

**Upstream:**
https://github.com/microsoft/TinyTroupe

**Disposition:**
External Python dependency. Do not vendor.

**Pinned commit:**
`a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4`

**Branch:**
release `v0.7.0`

**Usage:**
Pin in `pyproject.toml`:

```toml
dependencies = [
    "tinytroupe @ git+https://github.com/microsoft/TinyTroupe.git@a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4"
]
```

Blablador compatibility belongs in `services/persona_service`; never patch the
installed upstream package at application startup.

The Helmholtz client implementation on
`JsonLord/TinyTroupe:fix-openai-auth-error` was reviewed at commit
`cc9bd2e550d93ad867746c9dddffaf6ff13f6620`. That branch reports package version
0.5.2, so it is not substituted for the reviewed 0.7.0 runtime. Its provider
mapping is implemented at the persona-service adapter boundary instead:
`helmholtz-blablador` is normalized to TinyTroupe 0.7's registered `openai`
client, while `OPENAI_BASE_URL` points to the Helmholtz-compatible endpoint.

---

## AI-UX

**Repository:**
https://github.com/JsonLord/AI-UX

**Disposition:**
Reference only. Do not import as runtime dependency.

**Latest commit:**
`7f22b3734e671bae49980f0aca9868b799e711a6`

**Notes:**
Use as design and UX reference material.

---

## mkslides

**Repository:**
https://github.com/MartenBE/mkslides

**Disposition:**
External Python dependency. Do not vendor.

**Notes:**
Installed during Docker build. May require patching `pyproject.toml` for Python version compatibility.

---

## tiny_web

**Disposition:**
Legacy/export compatibility only. Do not merge into main workspace.

---

## agent-notes

**Disposition:**
Optional persona-data source. Do not merge unless explicitly required.
