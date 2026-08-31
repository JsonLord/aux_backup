# OpenDesign Hugging Face API testing report

Date: 2026-08-27  
Target: `https://open-design.ai/`  
Space: `Leon4gr45/aux-synthetic-ux-demo`

## Scope

The acceptance requested five personas and these read-only tasks:

1. Understand the product and primary value proposition.
2. Find installation or onboarding guidance.
3. Inspect examples, documentation, or source code.
4. Identify pricing, licensing, or usage constraints.
5. Locate support, community, or contact information.

## Service and API results

- The target returned HTTP 200.
- Space readiness reported the control plane, persona runtime, JourneyTest worker,
  and Eyeson worker ready, with model configuration and live execution readiness true.
- A Hugging Face personal access token was verified by `/api/whoami-v2` and restricted
  to the matching personal workspace; organization selection remains OAuth-only.
- Session `ses_4a7b08e4105e42ef90919e3c61563030` persisted five immutable persona snapshots,
  a `ux.report`, an HTML `ux.presentation`, and a `journey.log`.

## Evidence classification

The saved report from that completed control-plane job is **inferred**, not observed.
All five JourneyTest runs in that job recorded `runStatus: error` before capturing a
screenshot. Therefore its task-clarity findings are configuration checks and must not
be represented as verified usability findings about OpenDesign.

The live sequence exposed and fixed these deployment defects:

1. Gradio treated a single persona mapping as an iterable of strings.
2. Hugging Face personal tokens could deploy but could not authenticate the API.
3. TinyTroupe did not consume `OPENAI_MODEL` through its public config manager.
4. The configured model did not satisfy TinyTroupe's sampling-plan postcondition;
   the acceptance endpoint now permits an explicitly labelled deterministic fallback.
5. JourneyTest's built-in Pi catalog did not recognize the custom model ID; the adapter
   now supplies the pinned director with an OpenAI-compatible model contract.
6. Generated agent-browser session names exceeded the Unix socket-path limit.
7. Chrome required the container-scoped `--no-sandbox` launch argument.
8. The copied browser wrapper lacked executable mode in the built Space image.
9. Video finalization required `ffmpeg`.
10. A browser-directed run exceeded the original 120-second worker timeout.
11. A synchronous workflow response exceeded the Hugging Face proxy lifetime; the API
    now returns a persisted job ID and exposes job polling instead.

## Current conclusion

The API, tenancy, persona persistence, and downloadable report/presentation/log paths
are validated. Five persona snapshots were generated through the explicit offline
fallback and their behavior priors were compiled by the OpenAI-compatible semantic
boundary when the provider was available. A complete observed OpenDesign usability
verdict is **not yet available**: no run produced browser screenshots or Eyeson
findings. The outstanding acceptance step is to poll a new asynchronous job through
`GET /api/v1/jobs/{job_id}` until it finishes and require non-empty screenshot and
snapshot artifacts before treating the report as observed evidence.

Run the checked-in acceptance client after deploying the current revision:

```bash
HF_OAUTH_TOKEN=... WORKSPACE_ID=hf:user:... \
  bash scripts/test_hf_live_workflow.sh
```

The script fails unless the job succeeds and report, presentation, and journey-log
artifacts exist. Browser evidence must still be inspected separately before approval.
