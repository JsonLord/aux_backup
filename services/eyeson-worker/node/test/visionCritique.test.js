"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { captureSize, critiqueScreenshot, toPainPoint, buildPrompt, parseFindings, parseCritique,
  completeObjectsIn, visionMaxTokens, DEFAULT_VISION_MAX_TOKENS,
  VisionUnavailableError } = require("../src/visionCritique");
const { aggregateCohort } = require("../src/aggregate");

test("buildPrompt lists the page's elements by index, and does not show the selector", () => {
  // The reviewer is asked to point at a line number rather than to transcribe a
  // selector. An index is a thing it cannot make plausible -- 3 is either in
  // range or it is not -- while a selector it has never seen comes out as
  // confident CSS for some other website. It cannot transcribe what it is not
  // shown, so the selector is resolved from the index here instead.
  const { user } = buildPrompt({
    url: "https://example.com", task: "Find pricing",
    elements: [{ selector: "#buy-button", role: "button", text: "Buy now", boundingBox: { x: 10, y: 20, width: 80, height: 30 } }],
  });
  assert.match(user, /^0\. kind=button text="Buy now"/m);
  assert.match(user, /Cite one by its index number/);
  assert.match(user, /Buy now/);
  assert.match(user, /Find pricing/);
  assert.doesNotMatch(user, /#buy-button/, "the selector is ours to resolve, not the model's to copy");
  // One word meaning two things in one prompt is an invitation to conflate them:
  // the reviewer is asked for a `role` of its own, so the element's own type is
  // listed as `kind`.
  assert.doesNotMatch(user, /role=button/);
});

test("a citation is a line number, and an out-of-range one is not a citation", () => {
  const page = [{ selector: "e1" }, { selector: "e6" }, { selector: "span@316,533" }];
  const cite = (elements) => parseCritique(JSON.stringify({ issues: [{
    title: "T", description: "D", category: "usability", severity: "low", elements }], strengths: [],
  }), { elements: page }).issues[0].elements.map((item) => item.elementSelector);

  assert.deepEqual(cite([{ element: 1, role: "cause" }]), ["e6"]);
  // A number written as a string is still a number.
  assert.deepEqual(cite([{ element: "2", role: "cause" }]), ["span@316,533"]);
  // Out of range is caught by arithmetic rather than by recognising bad CSS.
  assert.deepEqual(cite([{ element: 97, role: "cause" }]), []);
  assert.deepEqual(cite([{ element: -1, role: "cause" }]), []);
  // A model that wrote the selector out anyway is not punished for it, as long as
  // the selector is real.
  assert.deepEqual(cite([{ elementSelector: "e1", role: "cause" }]), ["e1"]);
  assert.deepEqual(cite([{ elementSelector: "a.btn.btn-primary", role: "cause" }]), []);
});

test("parseFindings tolerates a markdown-fenced JSON array, normalizes elements/impact/alternatives, and rejects malformed entries", () => {
  const content = "```json\n"
    + '[{"category":"accessibility","severity":"high",'
    + '"elements":[{"elementSelector":"#buy-button","role":"trigger"},{"elementSelector":"#unknown","role":"bogus-role"}],'
    + '"title":"Low contrast","description":"Text fails WCAG AA contrast.",'
    + '"estimatedImpact":{"frustration":0.6,"confusion":"not-a-number","trust":1.4},'
    + '"alternatives":[{"proposedChange":"Darken the text color.","rationale":"Meets WCAG AA.","effort":"low"},{"proposedChange":""}]},'
    + '{"category":"nonsense","severity":"unknown"}]'
    + "\n```";
  const findings = parseFindings(content);
  assert.equal(findings.length, 1); // second top-level entry has no title/description, dropped
  const finding = findings[0];
  assert.equal(finding.category, "accessibility");
  assert.equal(finding.severity, "high");
  assert.equal(finding.elements.length, 2);
  assert.equal(finding.elements[0].role, "trigger");
  assert.equal(finding.elements[1].role, "cause"); // invalid role normalized to a safe default
  assert.equal(finding.estimatedImpact.frustration, 0.6);
  assert.equal(finding.estimatedImpact.confusion, 0); // non-numeric normalized to 0
  assert.equal(finding.estimatedImpact.trust, 1); // out-of-range clamped to 1
  assert.equal(finding.alternatives.length, 1); // the empty-proposedChange entry is dropped
  assert.equal(finding.alternatives[0].effort, "low");
});

test("critiqueScreenshot resolves elements to their real boundingBox and grounds the finding", async (t) => {
  t.mock.method(global, "fetch", async () => ({
    ok: true,
    json: async () => ({ choices: [{ message: { content: JSON.stringify([
      { category: "accessibility", severity: "medium",
        elements: [{ elementSelector: "#buy-button", role: "trigger" }],
        title: "Ambiguous button label", description: "The button text does not describe the action clearly.",
        estimatedImpact: { frustration: 0.3, confusion: 0.5, trust: 0.1 },
        alternatives: [{ proposedChange: "Use a more specific label like 'Complete purchase'.", effort: "low" }] },
    ]) } }] }),
  }));

  const { findings } = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "Buy an item",
    elements: [{ selector: "#buy-button", role: "button", text: "Buy", boundingBox: { x: 10, y: 20, width: 80, height: 30 } }],
    options: { apiKey: "test-key", baseUrl: "https://router.invalid/v1", model: "auto" },
  });

  assert.equal(findings.length, 1);
  assert.deepEqual(findings[0].elements[0].box, { x: 10, y: 20, width: 80, height: 30 });
  assert.ok(findings[0].grounding);
  assert.equal(global.fetch.mock.callCount(), 1);
  const [calledUrl, calledInit] = global.fetch.mock.calls[0].arguments;
  assert.equal(calledUrl, "https://router.invalid/v1/chat/completions");
  const sentBody = JSON.parse(calledInit.body);
  assert.equal(sentBody.messages[1].content[1].image_url.url, "data:image/png;base64,Zm9v");
});

test("critiqueScreenshot retries once on a transient failure then succeeds", async (t) => {
  let calls = 0;
  t.mock.method(global, "fetch", async () => {
    calls += 1;
    if (calls === 1) throw new Error("ECONNRESET");
    return { ok: true, json: async () => ({ choices: [{ message: { content: "[]" } }] }) };
  });
  const { findings } = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "Buy an item", elements: [],
    options: { apiKey: "test-key", baseUrl: "https://router.invalid/v1", model: "auto", retryWaitMs: 1 },
  });
  assert.deepEqual(findings, []);
  assert.equal(calls, 2);
});

test("critiqueScreenshot requires credentials rather than silently returning fake findings", async () => {
  const originalKey = process.env.OPENAI_API_KEY;
  const originalBlablador = process.env.BLABLADOR_API_KEY;
  delete process.env.OPENAI_API_KEY;
  delete process.env.BLABLADOR_API_KEY;
  try {
    await assert.rejects(
      critiqueScreenshot({ imageBase64: "Zm9v", url: "https://example.com", task: "t", elements: [], options: { baseUrl: "https://router.invalid/v1" } }),
      /OPENAI_API_KEY/,
    );
  } finally {
    if (originalKey !== undefined) process.env.OPENAI_API_KEY = originalKey;
    if (originalBlablador !== undefined) process.env.BLABLADOR_API_KEY = originalBlablador;
  }
});

test("toPainPoint shapes a critique finding into the full UXPainPoint record aggregateCohort expects", () => {
  const finding = {
    category: "accessibility", severity: "high", title: "Low contrast form labels",
    description: "Labels are hard to read against the background.",
    elements: [{ elementSelector: "#email-label", role: "trigger", box: { x: 5, y: 10, width: 60, height: 20 } }],
    estimatedImpact: { frustration: 0.4, confusion: 0.6, trust: 0.2 },
    alternatives: [{ proposedChange: "Increase label contrast to meet WCAG AA.", rationale: "Improves readability.", effort: "low" }],
    grounding: { status: "completed", references: [{ source: "W3C Web Accessibility Initiative" }] },
  };
  const painPoint = toPainPoint(finding, { runId: "run1", userId: "persona1", route: "https://example.com",
    stepId: "step-001", screenshotRef: "/tmp/run/screenshots/001.png", videoTimestampMs: 4200 });

  assert.equal(painPoint.runId, "run1");
  assert.equal(painPoint.userId, "persona1");
  assert.deepEqual(painPoint.stepIds, ["step-001"]);
  assert.equal(painPoint.screenshotRef, "/tmp/run/screenshots/001.png");
  assert.equal(painPoint.videoTimestampMs, 4200);
  assert.equal(painPoint.behavioralImpact.frustrationDelta, 0.4);
  assert.equal(painPoint.behavioralImpact.confusionDelta, 0.6);
  assert.equal(painPoint.behavioralImpact.trustDelta, -0.2); // trust erosion is a negative delta
  assert.equal(painPoint.elements[0].elementId, "#email-label");
  assert.equal(painPoint.elements[0].role, "trigger");
  assert.equal(painPoint.elements[0].contribution, 1);
  assert.equal(painPoint.diagnosis.category, "accessibility");
  assert.equal(painPoint.alternatives.length, 1);
  assert.deepEqual(painPoint.alternatives[0].addressesPainPointIds, [painPoint.id]);
  assert.equal(painPoint.overlays.length, 1);
  assert.deepEqual(painPoint.overlays[0].box, { x: 5, y: 10, width: 60, height: 20 });
});

test("vision-critique pain points from different personas aggregate into one synthesized root cause", () => {
  const findingFor = (frustration) => ({
    category: "accessibility", severity: "high", title: "Low contrast form labels",
    description: "Labels are hard to read against the background.",
    elements: [{ elementSelector: "#email-label", role: "trigger", box: { x: 5, y: 10, width: 60, height: 20 } }],
    estimatedImpact: { frustration, confusion: 0.5, trust: 0.1 },
    alternatives: [{ proposedChange: "Increase label contrast.", effort: "low" }],
    grounding: { status: "completed", references: [] },
  });
  const runs = [
    { runId: "run-ada", profileId: "ada", iterationId: "iteration-1", verdict: "passed",
      simulationProfile: { behavior: { patience: 0.8 } },
      painPoints: [toPainPoint(findingFor(0.3), { runId: "run-ada", userId: "ada", route: "https://example.com",
        stepId: "step-1", screenshotRef: "shots/ada-1.png" })] },
    { runId: "run-lin", profileId: "lin", iterationId: "iteration-2", verdict: "passed",
      simulationProfile: { behavior: { patience: 0.2 } },
      painPoints: [toPainPoint(findingFor(0.7), { runId: "run-lin", userId: "lin", route: "https://example.com",
        stepId: "step-1", screenshotRef: "shots/lin-1.png" })] },
  ];
  const rootCauses = aggregateCohort(runs);
  // Same title/elements/category from two different personas collapse into one
  // synthesized root cause instead of two separate per-persona findings.
  assert.equal(rootCauses.length, 1);
  assert.deepEqual(rootCauses[0].affectedUsers.sort(), ["ada", "lin"]);
  assert.equal(rootCauses[0].affectedIterations.length, 2);
  assert.equal(rootCauses[0].averageStateImpact.frustration, 0.5); // (0.3 + 0.7) / 2
});

test("parseCritique accepts the issues/strengths object and a legacy bare array", () => {
  const wrapped = parseCritique(JSON.stringify({
    issues: [{ category: "accessibility", severity: "high", title: "Low contrast",
      description: "Text is hard to read.", elements: [], estimatedImpact: {}, alternatives: [] }],
    strengths: [{ title: "Consistent buttons", description: "Every control uses the same rounded rectangle.",
      elements: [{ elementSelector: "#buy-button", role: "trigger" }] }],
  }));
  assert.equal(wrapped.issues.length, 1);
  assert.equal(wrapped.strengths.length, 1);
  assert.equal(wrapped.strengths[0].title, "Consistent buttons");
  assert.equal(wrapped.strengths[0].elements[0].elementSelector, "#buy-button");

  // A model that ignores the wrapper and returns a bare issues array is still usable.
  const legacy = parseCritique(JSON.stringify([{ category: "usability", severity: "low",
    title: "Nit", description: "Minor.", elements: [], estimatedImpact: {}, alternatives: [] }]));
  assert.equal(legacy.issues.length, 1);
  assert.deepEqual(legacy.strengths, []);
});

test("parseCritique drops malformed strengths rather than inventing praise", () => {
  const parsed = parseCritique(JSON.stringify({
    issues: [],
    strengths: [{ title: "Good icons" }, { description: "no title" }, null, "nope",
      { title: "Real one", description: "Actually described." }],
  }));
  assert.equal(parsed.strengths.length, 1);
  assert.equal(parsed.strengths[0].title, "Real one");
});

test("critiqueScreenshot returns strengths with resolved element boxes", async (t) => {
  t.mock.method(global, "fetch", async () => ({
    ok: true,
    json: async () => ({ choices: [{ message: { content: JSON.stringify({
      issues: [],
      strengths: [{ title: "Consistent buttons", description: "Rounded rectangles make clickability obvious.",
        elements: [{ elementSelector: "#buy-button", role: "trigger" }] }],
    }) } }] }),
  }));
  const { findings, strengths } = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "Buy an item",
    elements: [{ selector: "#buy-button", role: "button", text: "Buy", boundingBox: { x: 1, y: 2, width: 3, height: 4 } }],
    options: { apiKey: "test-key", baseUrl: "https://router.invalid/v1", model: "auto" },
  });
  assert.deepEqual(findings, []);
  assert.equal(strengths.length, 1);
  assert.deepEqual(strengths[0].elements[0].box, { x: 1, y: 2, width: 3, height: 4 });
});

test("buildPrompt asks for strengths as well as issues", () => {
  const { system } = buildPrompt({ url: "https://example.com", task: "Buy", elements: [] });
  assert.match(system, /"strengths"/);
  assert.match(system, /preserved/);
});


test("a provider outage is reported as unavailable, not as an invalid request", async (t) => {
  // A live run's report said only "Vision-based UX critique was attempted but
  // failed: HTTP Error 422: Unprocessable Entity". 422 reads as "your request was
  // malformed", so it sent the reader looking at the payload while the real cause
  // -- the model endpoint -- went unnamed. An outage and a bad request must not
  // answer with the same status.
  t.mock.method(globalThis, "fetch", async () => ({ ok: false, status: 502,
    text: async () => "Bad Gateway" }));
  const failure = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "t", elements: [],
    options: { apiKey: "k", baseUrl: "https://router.invalid/v1", maxAttempts: 1, retryWaitMs: 0 },
  }).then(() => null, (error) => error);

  assert.ok(failure instanceof VisionUnavailableError);
  assert.equal(failure.status, 502);
  assert.equal(failure.code, "vision_upstream_failed");
  assert.match(failure.message, /vision critique failed after 1 attempts/);
});

test("a payload the endpoint will always reject is not retried", async (t) => {
  // A live run spent three attempts and both backoffs on an HTTP 413 before
  // reporting a 502: the same oversized body cannot become acceptable on a
  // retry, and the retries hid the real cause behind "after 3 attempts".
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls += 1;
    return { ok: false, status: 413,
      text: async () => '{"error":{"message":"request entity too large","type":"PayloadTooLargeError"}}' };
  });

  const failure = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "t", elements: [],
    options: { apiKey: "k", baseUrl: "https://router.invalid/v1", maxAttempts: 3, retryWaitMs: 1000 },
  }).then(() => null, (error) => error);

  assert.ok(failure instanceof VisionUnavailableError);
  assert.equal(calls, 1, "413 must not be retried");
  assert.match(failure.message, /vision critique failed after 1 attempts/);
  assert.match(failure.message, /HTTP 413/);
});

test("a transient upstream failure is still retried", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls += 1;
    return { ok: false, status: 503, text: async () => "Service Unavailable" };
  });

  await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "t", elements: [],
    options: { apiKey: "k", baseUrl: "https://router.invalid/v1", maxAttempts: 3, retryWaitMs: 0 },
  }).then(() => null, (error) => error);

  assert.equal(calls, 3, "5xx keeps its retry budget");
});

test("a missing credential is reported as not configured, not as an invalid request", async () => {
  const original = { key: process.env.OPENAI_API_KEY, blablador: process.env.BLABLADOR_API_KEY };
  delete process.env.OPENAI_API_KEY;
  delete process.env.BLABLADOR_API_KEY;
  try {
    const failure = await critiqueScreenshot({
      imageBase64: "Zm9v", url: "https://example.com", task: "t", elements: [],
      options: { baseUrl: "https://router.invalid/v1" },
    }).then(() => null, (error) => error);

    assert.ok(failure instanceof VisionUnavailableError);
    assert.equal(failure.status, 503);
    assert.equal(failure.code, "vision_not_configured");
  } finally {
    if (original.key !== undefined) process.env.OPENAI_API_KEY = original.key;
    if (original.blablador !== undefined) process.env.BLABLADOR_API_KEY = original.blablador;
  }
});

test("a critique cut off at the completion budget keeps the findings it finished", () => {
  // The exact failure from a live run: max_tokens reached mid-string inside the
  // fourth finding, so JSON.parse rejected a body that already held three
  // complete, usable observations. Every screenshot in that run failed this way
  // and the report carried no vision findings at all.
  const truncated = JSON.stringify({
    issues: [
      { title: "Pricing is never stated", description: "No plan names a price.",
        severity: "high", category: "copy",
        elements: [{ elementSelector: "section:nth-of-type(3)", role: "cause" }] },
      { title: "Links have no accessible name", description: "Icon-only links carry no aria-label.",
        severity: "medium", category: "accessibility", elements: [] },
    ],
  }).replace(/\}$/, "")
    + ', {"title": "A third finding that was cut off mid-sen';

  const parsed = parseCritique(truncated, { truncated: true });
  assert.equal(parsed.truncated, true);
  assert.equal(parsed.issues.length, 2);
  assert.deepEqual(parsed.issues.map((issue) => issue.title),
    ["Pricing is never stated", "Links have no accessible name"]);
  // The finding that was cut off is dropped, not guessed at.
  assert.ok(!parsed.issues.some((issue) => /cut off/.test(issue.title)));
});

test("braces inside a description are not mistaken for structure", () => {
  const objects = completeObjectsIn('{"title":"Uses {placeholder} copy","description":"a } brace"}, {"title":"cut');
  assert.equal(objects.length, 1);
  assert.equal(objects[0].title, "Uses {placeholder} copy");
});

test("a cut-off critique with nothing complete says so, and says why", () => {
  assert.throws(() => parseCritique('{"issues": [{"title": "only the very begin', { truncated: true }),
    /cut off at the completion budget/);
  // And a body that was never JSON keeps its own, different explanation.
  assert.throws(() => parseCritique("I am sorry, I cannot analyse this image.", { truncated: false }),
    /did not return JSON/);
});

test("the completion budget has room for a full critique and can be overridden", () => {
  // 2500 was reached exactly, mid-finding, on a page with 52 detected elements.
  delete process.env.EYESON_VISION_MAX_TOKENS;
  assert.ok(visionMaxTokens() > 2500);
  process.env.EYESON_VISION_MAX_TOKENS = "1200";
  assert.equal(visionMaxTokens(), 1200);
  delete process.env.EYESON_VISION_MAX_TOKENS;
  process.env.EYESON_VISION_MAX_TOKENS = "not-a-number";
  assert.equal(visionMaxTokens(), DEFAULT_VISION_MAX_TOKENS);
  delete process.env.EYESON_VISION_MAX_TOKENS;
});

test("the prompt says what the element list is, and what the capture is", () => {
  // The vision critique produced the two most serious findings in a live report
  // and both were wrong: "the entire header and hero section repeats three times
  // vertically ... looks highly broken" (critical) over a page that renders once,
  // and "preventing users from seeing the actual price" (high) in the same report
  // whose verdict quotes the price. An earlier run filed "Massive empty vertical
  // sections ... a major rendering bug" over ordinary page whitespace in an
  // 8620px stitched capture.
  //
  // It already received the element list and was already told not to invent
  // elements. What it was never told is what the list *means*.
  const complete = buildPrompt({
    url: "https://example.test/", task: "find the price",
    elements: [{ selector: "e1", role: "link", text: "Home", boundingBox: {} }],
    capture: { width: 1280, height: 8620 },
  });

  assert.match(complete.user, /complete for this capture/);
  assert.match(complete.user, /each exactly once/);
  assert.match(complete.user, /1280x8620/);
  assert.match(complete.user, /stitched full-page image/);
  // The three claims the runs disproved, refused up front rather than caught after.
  assert.match(complete.system, /Do not report empty space, tall gaps or a page's length as a\s+rendering bug/);
  assert.match(complete.system, /a thing that is on the page twice is in the list twice/);
  assert.match(complete.system, /never that it prevented, blocked or stopped anyone/);
});

test("a truncated element list is not described as an inventory", () => {
  // "If something is not here, it is not on the page" is ground truth when the
  // list is complete and a falsehood when it is the first sixty of ninety.
  const many = Array.from({ length: 90 }, (_, index) => (
    { selector: `e${index}`, role: "link", text: `Item ${index}`, boundingBox: {} }));
  const sampled = buildPrompt({ url: "https://example.test/", task: "find it", elements: many });

  assert.match(sampled.user, /first 60 of 90/);
  assert.match(sampled.user, /sample rather than an inventory/);
  assert.doesNotMatch(sampled.user, /complete for this capture/);
});

test("the capture's size is read from the capture", () => {
  // A number travelling separately from the thing it describes is a number that
  // can be wrong about it.
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    Buffer.from([0, 0, 0, 13]), Buffer.from("IHDR"),
    (() => { const b = Buffer.alloc(8); b.writeUInt32BE(1280, 0); b.writeUInt32BE(577, 4); return b; })(),
  ]);
  assert.deepEqual(captureSize(png.toString("base64")), { width: 1280, height: 577 });
  // Anything it cannot read says nothing rather than guessing.
  assert.equal(captureSize("not an image"), null);
  assert.equal(captureSize(""), null);
});

test("naming the elements a finding is about is the default, not the exception", () => {
  // Across sixteen vision findings in four live reports, the elements array came
  // back empty every single time -- including both of the critical findings that
  // turned out to be wrong. The plumbing was never at fault: toPainPoint maps
  // elementSelector through and aggregate groups on it. The model was simply
  // taking the "empty array for a page-wide finding" branch every time, which
  // leaves a reader nothing to look at and leaves the claim anchored to nothing
  // that can be checked against a measurement.
  const { system } = buildPrompt({
    url: "https://example.test/", task: "find the price",
    elements: [{ selector: "e1", role: "link", text: "Pricing", boundingBox: {} }],
  });

  assert.match(system, /name every element the finding is about/);
  assert.match(system, /If you can say\s+where on the screen the problem is, say which elements/);
  // And what an empty array is allowed to mean.
  assert.match(system, /genuinely about the whole page/);
  assert.match(system, /not that pointing at the elements would have taken a moment longer/);
});

test("a cited selector that is not on the page is not a citation", () => {
  // Asking the reviewer to name the elements took citations from zero of sixteen
  // to eight of ten -- and every selector in that first batch was invented.
  // Against a Tailwind site whose element list is agent-browser refs ("e6",
  // "span@316,533") it produced Bootstrap: a.btn.btn-primary.btn-lg.mr-3,
  // h1.display-4.font-weight-bold.mb-3, div.col-md-6.text-center > p. Plausible
  // CSS for some other website.
  //
  // An invented citation is worse than none: it reads as corroboration, and a
  // reader has to go and look to find out it is not.
  const body = JSON.stringify({
    issues: [
      { title: "Low contrast", description: "Pale text.", category: "accessibility",
        severity: "high",
        elements: [{ elementSelector: "e6", role: "cause" },
                   { elementSelector: "a.btn.btn-primary.btn-lg.mr-3", role: "cause" },
                   // The same selector arrived three times in one live finding,
                   // which says nothing three times.
                   { elementSelector: "e6", role: "cause" }] },
      { title: "All invented", description: "Nothing real cited.", category: "usability",
        severity: "high",
        elements: [{ elementSelector: "h1.display-4.font-weight-bold.mb-3", role: "cause" }] },
    ],
    strengths: [{ title: "Clear hierarchy", description: "Good.",
                  elements: [{ elementSelector: "div.col-md-6", role: "cause" },
                             { elementSelector: "e1", role: "cause" }] }],
  });

  const parsed = parseCritique(body, { elements: [{ selector: "e6" }, { selector: "e1" }] });

  assert.deepEqual(parsed.issues[0].elements.map((item) => item.elementSelector), ["e6"]);
  // A finding whose every citation was invented is left citing nothing, which is
  // what "unanchored" already means elsewhere in the report.
  assert.deepEqual(parsed.issues[1].elements, []);
  // Strengths are held to it too: praise pointing at nothing is praise for nothing.
  assert.deepEqual(parsed.strengths[0].elements.map((item) => item.elementSelector), ["e1"]);
});

test("with no element list a named citation stands and an index resolves to nothing", () => {
  // Nothing to check against is not the same as a citation that failed a check,
  // and stripping every named citation on that basis would be the guard causing
  // the harm it exists to prevent.
  //
  // An index is the exception, because it is not a name: it is a lookup into a
  // list, and with no list there is nothing to look up. A live report carried
  // `elementId: null` on twenty-four citations across seven findings for exactly
  // this reason -- the screenshots had no paired DOM snapshot, so the element
  // list was empty and the indices passed straight through unresolved.
  const body = JSON.stringify({ issues: [{ title: "T", description: "D", category: "usability",
    severity: "low", elements: [{ elementSelector: "whatever", role: "cause" },
                                { element: 3, role: "cause" }] }], strengths: [] });

  const withoutList = parseCritique(body).issues[0].elements;
  assert.deepEqual(withoutList.map((item) => item.elementSelector), ["whatever"]);
  assert.ok(withoutList.every((item) => item.elementSelector),
    "a citation that resolves to nothing is not a citation");
});
