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

---

## JourneyTest

**Repository:**
https://github.com/Jules-Astier/journeytest-core

**Disposition:**
External npm dependency. Do not vendor.

**Version:**
`0.1.2`

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

**Current project fork:**
https://github.com/JsonLord/TinyTroupe

**Disposition:**
External Python dependency. Do not vendor.

**Pinned commit:**
`43d951eea015aea09972dc95537c9bbbc74ba207`

**Branch:**
`main`

**Usage:**
Pin in `pyproject.toml`:

```toml
dependencies = [
    "tinytroupe @ git+https://github.com/JsonLord/TinyTroupe.git@43d951eea015aea09972dc95537c9bbbc74ba207"
]
```

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
