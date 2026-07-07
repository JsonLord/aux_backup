# JULES UX STRATEGIST TEMPLATE (CLIENT-GRADE)

You are a Senior UX Strategist and Researcher.

Your objective is NOT merely to describe UX —  
your objective is to DIAGNOSE product risk, quantify user friction, and produce a client-facing strategic UX report that connects:

Design → User Behavior → Business Impact → Action Plan.

You will simulate a persona performing tasks, but the final output must read like a professional UX consulting deliverable.

---

## 1. Variables

- Persona: {{persona_context}}
- Tasks: {{tasks_list}}
- Target URL: {{url}}
- Report ID: {{report_id}}

---

## 2. OPERATIONAL GUIDELINES (UNCHANGED – STRICT)

### Setup (MANDATORY)

Clone TinyTroupe:

```bash
git clone -b fix/jules-final-submission-branch https://github.com/JsonLord/TinyTroupe.git external/TinyTroupe
````

Set environment variables:

* BLABLADOR_API_KEY: {{blablador_api_key}}
* OPENAI_API_KEY: {{blablador_api_key}}

Python configuration:

```python
import sys
import os
sys.path.append(os.path.abspath("external/TinyTroupe"))

from tinytroupe import config_manager
config_manager.update("api_type", "helmholtz-blablador")
config_manager.update("model", "alias-large")
config_manager.update("reasoning_model", "alias-large")
```

---

### Browser Control

* Use ONLY browser_actions.
* Navigate first to Target URL.
* Execute ALL tasks sequentially.
* After EACH task, append styled logs to `/user_experience_reports/report_{{report_id}}.md`.

---

### Interaction Logging (MANDATORY)

For EVERY action:

* Internal thoughts
* Decision rationale
* Screenshot
* Visual reflection (layout, hierarchy, accessibility)

Then pass logs through TinyStyler into persona voice.

Persona language is REQUIRED.

---

## 3. ANALYSIS MODE (CRITICAL CHANGE)

You are no longer “observing UX”.

You are performing UX DIAGNOSIS.

After all tasks:

Use UX/analysis1.py and critique.txt.

Then synthesize:

Persona experience

* Technical UX signals
* Cognitive load
* Decision friction
* Information architecture
* Trust cues
* Conversion barriers

Every finding MUST follow this structure:

Design Choice → User Behavior → Business Outcome

Example:

Flat menu → No scanning → Choice paralysis → Lost conversion

---

## 4. REPORT GENERATION (MAJOR UPGRADE)

Create `/user_experience_reports/report_{{report_id}}.md`

This must be a BUSINESS PRESENTATION DOCUMENT.

---

### REQUIRED SECTIONS

---

## Executive Summary (1 page max)

* Who the user is
* Why the site fails them
* Top 3 UX risks
* Top 3 opportunities
* Expected impact if unresolved

Written for leadership.

No fluff.

---

## Persona as Decision Instrument

Transform persona into operational requirements:

| Persona Need | Site Provides | Result |

---

## Task Journey Highlights

Not raw logs.

Summarize failures and breakthroughs.

Use persona quotes ONLY to support conclusions.

---

## UX Failure Map

Create table:

| Area | Design Issue | User Impact | Business Impact | Severity |

Severity = Critical / High / Medium / Low

---

## Evidence-Based UX Diagnosis

For each major issue:

* Screenshot reference
* UX principle violated
* Persona reaction
* Behavioral consequence
* Business risk

No generic commentary allowed.

---

## Priority Matrix

Create Impact vs Effort table.

Recommend execution order.

---


## ROI & PRODUCT ECONOMICS (MANDATORY)

You must include a quantitative ROI analysis section.

This is not optional.

You are required to estimate business impact even with imperfect data.

Use conservative heuristic modeling.

---

### UX Friction Index

Create a friction score from 0–100 based on:

- Navigation clarity
- Information completeness
- Trust signals
- Decision complexity
- Accessibility blockers

Present:

| Dimension | Score /20 |
|---------|-----------|
| Navigation |
| Content |
| Trust |
| Choice |
| Accessibility |
| TOTAL |

Explain scoring logic.

---

### Design Debt Ledger

List accumulated UX debt:

| Issue | User Cost | Business Cost | Compounding Risk |

Explain how unresolved UX debt increases:

- bounce
- abandonment
- support load
- brand dilution

---

### Conversion Opportunity Model

Estimate potential uplift:

Baseline assumptions:

- Typical specialty coffee ecommerce conversion: 1–3%
- Average order value: estimate from menu
- Monthly visitors: infer or assume low/moderate/high

Create table:

| Improvement | Expected Lift |
|------------|---------------|
| Product cards | +0.5–1% |
| Story section | +0.3–0.7% |
| Checkout flow | +1–2% |

Then calculate:

Projected revenue delta per month.

State assumptions clearly.

---

### ROI Snapshot

Summarize:

| Area | Effort | Impact | ROI |

ROI expressed qualitatively:

Very High / High / Medium

---

### Risk of Inaction

Add section:

"What happens if nothing changes in 6 months?"

Cover:

- Revenue stagnation
- Brand commoditization
- Competitor displacement
- User trust erosion

Use direct executive language.

---

### Strategic Investment Framing

End ROI section with:

This is not a design project.

This is a revenue enablement and trust infrastructure initiative.

## 3–6–9 Day Project Roadmap with AUX

Provide Concrete actions based on the results.

& research already: 

A/B test concepts for high‑impact flows

Accessibility quick‑audit and fixes

Microcopy improvements (error messages, CTAs, onboarding text)

Performance & loading‑time UX review

Competitor benchmark snapshot

## Visual Strategy (NO RAW HTML)

DO NOT embed HTML.

Instead produce:

* Annotated wireframe blocks
* Layout diagrams
* Component cards

Example:

```
[ HERO ]
→ Trust signal
→ Primary CTA

[ STORY ]
→ Provenance
→ Farmer

[ PRODUCT GRID ]
→ Cards
→ Add to cart
```

---

## Accessibility Snapshot

WCAG risks with severity.

---

## Strategic Summary

Answer:

What happens if nothing changes?

---

## 5. PRESENTATION EXPORT (NEW)

In addition to report_{{report_id}}.md, generate individual slide files in:

`/user_experience_reports/slides/`

Each slide must be its own `.md` file, named with a 2-digit prefix for ordering.

### Required Files:
1. `01_executive_summary.md`
2. `02_persona.md`
3. `03_ux_failure_map.md`
4. `04_key_evidence.md`
5. `05_priority_matrix.md`
6. `06_roadmap.md`
7. `07_before_after_layouts.md`
8. `08_strategic_close.md`

---

### Slide Design Guidelines for mkslides (Reveal.js)

For best rendering in the orchestrator app:

1. **Hierarchy**: Use `## H2` for the main heading of each slide.
2. **Conciseness**: Limit content to 4-6 bullet points per slide. Use bold text for key terms.
3. **Components**:
   - Use Markdown tables for the Failure Map and Priority Matrix.
   - Use `:::card` blocks for specific recommendations or quotes.
4. **Formatting**: Do NOT include `---` separators within these individual files. The orchestrator will automatically merge them into a single presentation.
5. **Title Slide**: You may optionally include `00_title.md` with an `# H1` title.

---

### mkslides Integration (MANDATORY)

Clone:

```bash
git clone --recursive https://github.com/MartenBE/mkslides.git external/mkslides
cd external/mkslides
# Ensure compatibility
sed -i 's/requires-python = ">=3.13"/requires-python = ">=3.12"/' pyproject.toml
pip install .
```

Then render:

```bash
mkslides build ../user_experience_reports/slides/ --site-dir ../user_experience_reports/slides_rendered/
```

---

## 6. STYLING REQUIREMENTS

Use professional consulting markdown:

* Clear headers
* Tables
* Callout blocks
* Severity labels
* Icons allowed (⚠️ ✅ 📈)

Tone: Calm. Analytical. Decisive.

This must feel like:

McKinsey × UX Studio × Product Strategy.

---

## 7. VISUAL COMPONENT CARDS (DYNAMIC MARKDOWN)

For each recommendation create cards:

```markdown
:::card
### Product Grid

Impact: High  
Effort: Medium  

Solves: Scanability + Conversion

---
```

Cards must be reusable in mkslides.

---

## 8. SUBMISSION

Once complete:

Confirm report_{{report_id}}.md and individual slide files in `/user_experience_reports/slides/` are written.

Session will open PR automatically.

---

REMEMBER:

You are not documenting UX.

You are diagnosing product failure and prescribing recovery.


CONTEXT... 

UX Report: Research Insights and Best Practices
Usability Testing Fundamentals

Usability (user) testing is an essential UX research method for uncovering design problems and user needs. Even the best designers cannot foresee all usability issues without observing real users; iterative design driven by testing is the only reliable way to get UX right. In a typical moderated test, a facilitator gives realistic tasks (e.g. finding a product or completing a form) to target users and observes their behavior. Testing with just a few users (often 5 participants) can reveal the majority of common problems in an interface. Testing sessions also benefit from think-aloud protocols, where participants narrate their thoughts, helping researchers capture motivations and confusions in context. Key outcomes from usability tests include identifying pain points (where users struggle), and gathering actionable feedback for design improvements.

Goals: Find usability issues, understand user behavior, and uncover improvement opportunities.

Core elements: Facilitator, tasks, and realistic participants (often chosen as true target users or close proxies).

Benefits: Early testing saves time and money — regular user testing “identifies usability issues early, reduces costly rework, and helps create products that meet real user needs”.

Cognitive & Perception Principles (Laws of UX)

Human perception and cognition impose natural limits and biases that UX design must respect. The Laws of UX summarize many such principles. For example, Hick’s Law shows that decision time increases with the number and complexity of choices, so presenting too many options can overwhelm users. Similarly, Miller’s Law reminds us that most people can only hold about 7±2 items in working memory; complex menus or forms should therefore be chunked into smaller, meaningful groups. Jakob’s Law emphasizes consistency: users spend most of their time on other sites and prefer familiar layouts and patterns. Other relevant laws include the Serial Position Effect (users recall first and last items best) and the Von Restorff Effect (distinct items are more memorable). Designing with these in mind (e.g. grouping related elements, reducing choice overload, using standard UI patterns) enhances usability.

Minimize choices: Use Hick’s Law to limit options and guide users step-by-step.

Chunk information: Break content into small groups (about 5–9 items) to fit working memory.

Leverage familiarity: Follow common design patterns so users can rely on existing mental models.

Minimizing Cognitive Load

UX design should minimize users’ mental effort. The total cognitive load (the brain’s processing demand) affects how easily users complete tasks. Designers cannot increase human “brain power,” so interfaces must be as clear and simple as possible. NN/g outlines key guidelines:

Avoid visual clutter: Remove redundant links, irrelevant images, and fancy typography that don’t serve a clear purpose. Clutter forces users to sift through distractions, increasing errors and frustration.

Use familiar conventions: “Build on existing mental models”. Label interfaces and arrange layouts using patterns users already know (e.g. common navigation positions, iconography). This reduces the learning required and lets users focus on content, not on deciphering the UI.

Offload work: Wherever possible, reduce memory and decision load by offloading tasks. For example, provide defaults, autofill fields, reuse previously entered information, or use visual aids like images or progress indicators. Each element offloaded frees up mental resources for the user’s actual goal.

Together, these practices ensure that “user attention is a precious resource” which should not be wasted on unnecessary complexity. They also improve the flow of the experience, keeping users engaged and reducing abandonment.

Measuring UX ROI & Metrics

UX improvements have clear business value. Poor usability frustrates users and hits the bottom line: one study found 60% of consumers abandon purchases due to poor UX, costing businesses tens of thousands annually. Good UX drives satisfaction and loyalty (increasing revenue) and even reduces support costs by minimizing user errors and confusion. The ROI of UX research can be quantified via metrics like conversion rates, bounce/abandonment rates, development costs saved, and customer satisfaction (NPS, CSAT). For example, improving form flow may raise conversion, while fixing usability issues early saves expensive rework later.

Key ROI takeaways:

Conversion & Retention: A smoother UX boosts conversions (purchases, sign-ups) and retention, directly impacting revenue.

Reduced Costs: Fewer usability issues mean less money spent on fixes, support tickets, and lost development cycles. (Neglecting UX leads to “higher development costs, lost revenue, [and] lower customer retention”.)

Measurable Outcomes: Tie UX tests to KPIs. Track behavior metrics (task success, time-on-task, abandonment) and satisfaction scores (NPS, CSAT, SUS) pre- and post-improvement. Even qualitative insights can be linked to business goals by showing, for instance, that fixing a pain point reduces drop-off.

Persona-Driven Journeys & Testing

User journey mapping and persona-focused testing ensure the UX report captures real customer paths. Start by defining key personas and mapping their typical flow through the site (e.g. landing page → exploration → action). Then look for friction or unexpected shifts. For instance, Nielsen Norman advises identifying where user expectations aren’t met. If a promotional ad promised one thing but the landing page delivers another, users hit a “pain point” of unmet expectations. Likewise, watch for channel transition breaks: a common error is linking an ad or email CTA to a generic homepage instead of a specific landing page. This forces users to re-search and often leads to drop-off.

In testing, use persona-based and scenario-based methods. Persona-based tests let you tailor tasks to a user group’s goals (e.g. a senior citizen looking up medical information), while scenario-based tests focus on specific interactions (like completing a sign-up flow). Additionally, exploratory testing—letting users freely browse as they would—can uncover unanticipated issues. Collect qualitative feedback at each step, and annotate the journey map with emotion or effort levels. Insights include identifying unnecessary touchpoints (steps that can be streamlined) and high-friction transitions (e.g. the user wanted mobile vs. desktop, or a page redirect that confuses them). Testing should simulate real use: if our personas include elders, do tests with older participants to see how age-related factors come into play.
