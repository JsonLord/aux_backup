# What the product has to be good at

Ten things a run is judged on, in the order a run produces them. The list came
from a review of a live run against a real site; it was carried in conversation
and lost, so it lives here now.

Each entry says what "good" means, what is actually built, and what is still
missing. A claim here is worth nothing without the evidence beside it, so
measurements name the run or the test that produced them.

---

## 1. The tasks fit the site

**Good:** every task refers to something that exists on the page.

**Built.** Tasks are written after fetching and summarising the page
(`app.py:generate_tasks`, `apps/gradio/page_summary.py`). Given only a URL the
model invented the site: against a real target it produced "Navigate to the
'Productivity for AEC' section" and "Explore the 'Solutions' menu" for a site
whose navigation is Home / How it works / Install / Research / Pricing. The
prompt now carries the real outline and forbids inventing navigation. When the
page cannot be read the tasks stay deliberately general and the status says so,
because tasks written blind are worth less and a reader should know which kind
they got.

**Also built:** a batch is checked against the outline it was written from
(`page_summary.tasks_that_invent_the_site`), and one that names places the page
does not have comes back with those names quoted and one more attempt. Both
inventions the live run produced are caught; "look for a way to contact a human,
and note whether one exists" is not, because that is the behaviour the prompt asks
for. A batch that never comes back clean is still used, with a line saying so:
ten real tasks with one invented section beat ten numbered placeholders.

## 2. The thoughts are a person's, not an agent's

**Good:** the record reads like someone thinking, not like a tool log.

**Built.** Every step is a cognitive cycle: what is visible, what is expected,
one action, what was observed, whether it matched, and the gap
(`personaDirector.js`, `personaActor.js`). The expectation is committed to
*before* acting, which is what makes the step falsifiable — a vague expectation
cannot turn out wrong. The persona is told not to describe how it feels: feelings
are derived from what the page does to it, never reported by the model.

**Evidence:** a live run recorded "I expect to see specific pricing plans, what
features are included in each plan" → observed → `matched: "no"` → a gap naming
what was absent.

## 3. Tool calling is correct

**Good:** the persona chooses an action; something turns it into driver calls.

**Built.** Actions are declared by the tools that implement them, TinyTroupe's
arrangement (`faculty.js`): each tool answers what actions it offers, what rules
govern them, and whether it can carry one out. The vocabulary the persona is
given is generated from those declarations, so an action offered and not
implemented — or implemented and never offered — cannot happen. A test asserts
the two sets are equal. An action nothing claims is reported rather than falling
through to a silent no-op.

## 4. The persona resembles itself

**Good:** the LLM behaves like this person, not like a helpful agent.

**Built, and this is the foundation.** Three tiers:

- **Within a step:** the action is scored against the persona and, below 7/10,
  the criticism goes back and another is asked for (`adherence.js`, TinyTroupe's
  `ActionGenerator`). Measured live: `READ the entire philosophy section twice`
  for a persona with `patience 0.20` scored **1/10** — "Low patience makes such
  lengthy rereading unlikely"; the correction scored **10/10**.
- **Across steps:** recurring criticism is consolidated into standing lessons in
  the persona's own voice (`memoryBank.js`, TinyTroupe's memory-as-faculty).
  Measured over two visits: mean adherence **5.7 → 6.6**, reaching `GIVE_UP` at
  10/10 by the third step of the second visit.
- **Offline:** the judgements are a GEPA trainset
  (`services/persona_service/actor_program.py`).

**Missing:** the GEPA compile has not been run against a real corpus, so the
third tier is built and unproven.

## 5. Physical traits are real

**Good:** an ability slider changes what happens, not what the prompt says.

**Built.** `physical.js` had published a colour matrix, a blur radius and a
contrast slope since the beginning and only ever produced a *manifest* of them.
The perception service applies them to the actual pixels before anything reads
the page (`services/perception_service/optics.py`), so an element that does not
survive is not detected, does not reach the persona, and cannot be acted on.

**Evidence, on a real Chromium rendering:** sharp eyes resolve all six elements;
mild impairment (0.7 acuity, 0.6 contrast) still resolves all six; poor eyes
(0.35 / 0.25) lose exactly the `#999` body copy and the `#aaa` fine print and
keep the heading, the call to action and the normal-contrast link. Finding real
problems means not making every page unusable for anyone with less than perfect
sight.

## 6. The report is specific, and says how to fix things

**Good:** a reader learns what is wrong, for whom, and what to change.

**Partly built.** Findings come from JourneyTest's own verdict plus the vision
critique. Two classes that exist nowhere else now reach the report as well
(`_pain_points_from_perception`): **present but not perceivable**, measured on
the rendered pixels after this person's optics; and **legible, on screen, and
never looked at**, which is the answer to "why did they not click the thing that
was right there". Grouped per element, not per step. The executive summary names
the worst finding instead of only counting.

**Missing:** severities are assigned by rule, not judged. Recommendations for the
two new classes are templated rather than written for the specific page.

## 7. Artifacts render correctly

**Good:** every screenshot, video and snapshot a finding cites actually opens.

**Partly built.** A run's evidence survives a bad ending
(`_usable_journey`), and a stitched full-page capture that repeated its own hero
band roughly fourteen times — reported by the vision stage as a CRITICAL
"infinite repeating page content" defect in the customer's site — is detected and
trimmed.

**Also built:** an eyesight finding now cites the page *as that person's eyes
delivered it*, not a clean screenshot of the page. The service could produce that
image from the start and nothing ever asked for it -- the request field was
dropped in the client on the way through. It is written only for steps that found
something unreadable, because a JPEG per step of a forty-step run is a lot of
bytes for a picture nothing will cite.

**Still missing:** no end-to-end check that every artifact reference in a
finished report resolves to a file that exists.

## 8. The slide deck fits the screen

**Good:** a deck opens without clipping or overflowing.

**Partly built.** Oversized presentation images on landscape screens were fixed.

**Not verified this session.** No check that a generated deck renders inside its
viewport at the sizes people actually use.

## 9. The run can be watched and taken over

**Good:** a person can see what the run sees and step in.

**Built.** A side-by-side live view over agent-browser's WebSocket stream, a real
pointer drawn into the page, and a takeover path. Stored browser sessions let a
run test the signed-in product rather than the logged-out one.

**Deferred:** pointer movement between clicks is not forwarded, so the cursor
teleports (task #22).

## 10. It runs unattended

**Good:** the pipeline finishes, or says exactly why not.

**Partly built.** Evidence is salvaged rather than discarded when a run ends
badly; a stumbling model call is retried; a completion cut off by a router that
spent its budget on hidden reasoning is salvaged rather than thrown away
(measured: `finish_reason: length` at 29 completion tokens against a budget of
800). The adherence gate reports itself unavailable after two consecutive
failures rather than silently passing everything.

**Missing:** the `alias-code` provider failure is recorded but not reported
upstream (task #24).
