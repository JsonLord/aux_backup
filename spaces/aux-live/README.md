---
title: AUX Live Synthetic UX Lab
emoji: 🧭
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
hf_oauth: true
pinned: false
---

# AUX live synthetic UX lab

This Space packages the repository's Gradio application, control plane, persona
runtime, and Journey worker in one container while retaining their versioned HTTP
boundaries. Generated personas can be inspected and tuned in **Persona Studio**.

Live JourneyTest execution requires the Space secrets documented in
`docs/hf-workspaces.md` and `docs/hf-space-live.md`. Browser evidence is never
represented as observed unless the Journey worker successfully returns it.
