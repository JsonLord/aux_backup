"use strict";
/**
 * What this person has already been told about themselves.
 *
 * The adherence gate corrects one action and forgets. The same persona makes the
 * same off-persona move on the next step, is corrected again, and pays for the
 * correction every time -- so a run gets no better as it goes, and neither does
 * the next one.
 *
 * TinyTroupe's answer is that memory is a mental faculty like any other:
 * TinyMemory extends TinyMentalFaculty, and a MemoryProcessor consolidates raw
 * episodes into something lasting. This follows that exactly. Every judged
 * action is stored as an episode; flaws that keep recurring are consolidated
 * into standing lessons about this person; and because the bank is a faculty,
 * those lessons reach the persona through actionsConstraintsPrompt -- the same
 * channel the browser uses to say what a click is. Nothing special-cases them.
 *
 * Two things are kept, not one. What the person keeps getting wrong is the
 * obvious half. What they got right is the more useful half: an example of an
 * action that scored ten out of ten steers far better than a list of
 * prohibitions, which is a lesson about writing instructions for people as much
 * as for models.
 */

const { existsSync, mkdirSync, readFileSync, writeFileSync } = require("node:fs");
const path = require("node:path");

const { Tool } = require("./faculty");

// A flaw seen once is a bad step; seen twice it is a pattern worth telling them
// about. Lower than this and a single unlucky judgement rewrites the persona.
const RECURRENCE = 2;

// Room for a few standing lessons, not a manual. Past this the prompt is mostly
// self-criticism and the persona reads as anxious rather than characterful.
const MAX_LESSONS = 4;
const MAX_EXEMPLARS = 2;

// At or above this, the judge found nothing worth saying and any flaw text is
// pro forma. Below it, a complaint is a complaint whether or not the step passed.
const LESSON_CEILING = 9;

// How many episodes are worth keeping per persona. Consolidation reads them all,
// so this bounds both the file and the work.
const MAX_EPISODES = 400;

/**
 * Turning a judge's criticism into something a person can act on.
 *
 * Measured, and it mattered: consolidating raw flaws made the persona worse --
 * mean adherence over a live visit fell from 6.0 to 4.3 with the bank switched
 * on. The lesson it had stored was "He'd likely skip vague sections instead of
 * scrolling through them", and it failed twice over. It is written in the third
 * person about a hypothetical, dropped into a prompt that speaks to the persona
 * as "you", so it reads as somebody else's opinion. And it forbids without
 * naming an alternative -- "skip" is not something the persona can do -- so the
 * only effect is noise, and it went on scrolling.
 *
 * A lesson has to say what this person does, in their own voice, in the
 * vocabulary they actually have. One call when a lesson is first consolidated,
 * not one per step.
 */
const LESSON_SYSTEM = `You turn criticism of someone into a short fact about who they are.

You are given several complaints about the same person's behaviour, and the list
of actions available to them. Write ONE sentence, addressed to them as "you",
saying what they do -- naming an action from the list they would take instead.

Say what they DO, never only what they do not do: "You give up on a page that
will not name a price" steers; "you would not keep scrolling" does not.

At most 20 words. Reply with the sentence and nothing else.`;

const STOP_WORDS = new Set(["a", "an", "and", "the", "this", "that", "would", "not", "such",
  "with", "for", "his", "her", "their", "them", "they", "who", "which", "makes", "make", "is",
  "are", "be", "of", "to", "in", "on", "it", "its", "very", "more", "most", "than"]);

/** The words in a criticism that say what it is about. */
function gist(flaw) {
  return new Set(String(flaw || "").toLowerCase().match(/[a-z]{3,}/g)?.filter(
    (word) => !STOP_WORDS.has(word)) || []);
}

/**
 * Whether two words are the same word.
 *
 * Exact matching is useless here and the failure is instructive: the two
 * criticisms "low patience makes such lengthy rereading unlikely" and "his
 * extreme impatience makes reading more vague copy improbable" are plainly the
 * same complaint and share not one token -- patience against impatience,
 * reading against rereading. A judge writing in its own words every time will
 * never repeat itself exactly, so a consolidator that needs it to never
 * consolidates anything.
 */
function sameWord(first, second) {
  if (first === second) return true;
  const [shorter, longer] = first.length <= second.length ? [first, second] : [second, first];
  if (shorter.length < 4) return false;
  // One inside the other covers the prefix and the negation alike.
  return longer.includes(shorter);
}

/** Whether two criticisms are the same criticism written twice. */
function sameComplaint(first, second, threshold = 0.34) {
  const [a, b] = [[...gist(first)], [...gist(second)]];
  if (!a.length || !b.length) return false;
  const shared = a.filter((word) => b.some((other) => sameWord(word, other))).length;
  return shared / Math.min(a.length, b.length) >= threshold;
}

class PersonaMemoryBank extends Tool {
  /**
   * @param {object} [options]
   * @param {string} [options.personaId]  what the bank is about; without one it
   *                                      stays in memory for this run only
   * @param {string} [options.root]       AUX_MEMORY_ROOT, where banks are kept
   */
  constructor({ personaId = "", root, episodes, rewrite, vocabulary = "" } = {}) {
    super({ name: "What you have learned about yourself",
      description: "Standing lessons from how this person has acted before" });
    this.personaId = String(personaId || "").replace(/[^A-Za-z0-9_.-]/g, "_");
    this.root = root ?? process.env.AUX_MEMORY_ROOT ?? "";
    this.episodes = episodes || this.load();
    // Given a rewriter, a recurring criticism becomes a fact about this person
    // before it is ever shown to them. Without one the raw flaw is used, which
    // is measurably worse than nothing -- see LESSON_SYSTEM above.
    this.rewrite = rewrite;
    this.vocabulary = vocabulary;
    this.phrasings = new Map();
  }

  get file() {
    if (!this.root || !this.personaId) return "";
    return path.join(this.root, `${this.personaId}.json`);
  }

  load() {
    if (!this.file || !existsSync(this.file)) return [];
    try {
      const parsed = JSON.parse(readFileSync(this.file, "utf8"));
      return Array.isArray(parsed?.episodes) ? parsed.episodes : [];
    } catch {
      // A bank that cannot be read is a bank that is not there. Losing the
      // lessons costs a little steering; refusing to run costs the whole test.
      return [];
    }
  }

  save() {
    if (!this.file) return false;
    try {
      mkdirSync(path.dirname(this.file), { recursive: true });
      writeFileSync(this.file, JSON.stringify({
        personaId: this.personaId, updatedAt: new Date().toISOString(),
        episodes: this.episodes.slice(-MAX_EPISODES),
      }, null, 1));
      return true;
    } catch {
      return false;
    }
  }

  /** One judged action, kept as it happened. TinyTroupe's episodic half. */
  store({ action, visible = "", expectation = "", score, flaw = "", passed }) {
    if (!action?.type || !Number.isFinite(Number(score))) return false;
    this.episodes.push({
      at: new Date().toISOString(),
      action: { type: action.type, target: action.target || "", content: action.content || "" },
      visible: String(visible).slice(0, 200), expectation: String(expectation).slice(0, 200),
      score: Number(score), flaw: String(flaw).slice(0, 200), passed: Boolean(passed),
    });
    if (this.episodes.length > MAX_EPISODES) this.episodes = this.episodes.slice(-MAX_EPISODES);
    return this.save();
  }

  /**
   * The episodes worked into things worth telling this person.
   *
   * TinyTroupe's consolidator, doing the one job that matters here: a criticism
   * that keeps coming back is not a bad step, it is something true about the
   * person that the prompt never said.
   */
  lessons() {
    const groups = [];
    for (const episode of this.episodes) {
      // Any criticism counts, not only the ones that failed the gate. A step
      // that passed at 7 out of 10 still had something found wrong with it, and
      // in a live visit those near-misses were most of the signal: of four
      // steps, the two that failed carried unrelated complaints while the two
      // that passed both complained about the same thing, and discarding them
      // left the persona with nothing learned at all.
      if (!episode.flaw || episode.score >= LESSON_CEILING) continue;
      const group = groups.find((candidate) => sameComplaint(candidate.flaw, episode.flaw));
      if (group) {
        group.count += 1;
        // Keep the shortest phrasing: the same complaint said briefly is the one
        // worth putting in front of somebody every turn.
        if (episode.flaw.length < group.flaw.length) group.flaw = episode.flaw;
        group.actions.add(episode.action.type);
      } else {
        groups.push({ flaw: episode.flaw, count: 1, actions: new Set([episode.action.type]) });
      }
    }
    return groups
      .filter((group) => group.count >= RECURRENCE)
      .sort((first, second) => second.count - first.count)
      .slice(0, MAX_LESSONS)
      .map((group) => ({ lesson: group.flaw, seen: group.count, after: [...group.actions] }));
  }

  /**
   * Put every standing lesson into the persona's own voice, once each.
   *
   * Called by the run before the lessons are shown. Cached by the complaint it
   * came from, so a lesson costs one call the first time it becomes a lesson and
   * nothing on every step afterwards.
   */
  async consolidate() {
    if (!this.rewrite) return;
    for (const item of this.lessons()) {
      if (this.phrasings.has(item.lesson)) continue;
      const complaints = this.episodes
        .filter((episode) => !episode.passed && episode.flaw
          && sameComplaint(episode.flaw, item.lesson))
        .slice(-4).map((episode) => `- ${episode.flaw}`).join("\n");
      try {
        const said = await this.rewrite({
          system: LESSON_SYSTEM,
          user: `COMPLAINTS ABOUT THEM:\n${complaints}\n\n`
            + `ACTIONS AVAILABLE TO THEM:\n${this.vocabulary || "(not given)"}`,
        });
        const sentence = String(said || "").trim().replace(/^["'\s]+|["'\s]+$/g, "").split("\n")[0];
        // A rewrite that came back empty, or as another third-person complaint,
        // is worse than the flaw it replaces -- so it has to look like advice
        // addressed to them before it is kept.
        if (sentence && /\byou\b/i.test(sentence)) this.phrasings.set(item.lesson, sentence);
      } catch {
        // A rewriter that is down leaves the lesson unspoken rather than
        // showing the persona a criticism written about somebody else.
        this.phrasings.set(item.lesson, "");
      }
    }
  }

  /** Actions that scored full marks: what being this person looks like done right. */
  exemplars() {
    return this.episodes
      .filter((episode) => episode.passed && episode.score >= 9)
      .slice(-MAX_EXEMPLARS)
      .map((episode) => ({ action: episode.action, expectation: episode.expectation }));
  }

  get actionTypes() {
    return [];      // it steers actions, it does not carry any out
  }

  actionsDefinitionsPrompt() {
    return "";
  }

  /**
   * The lessons, as the persona receives them.
   *
   * Written as statements about who they are rather than rules they must follow.
   * "You do not settle in and read long marketing copy" is a fact about a person;
   * "you must not READ twice" is an instruction to a machine, and a persona given
   * instructions starts sounding like one.
   */
  actionsConstraintsPrompt() {
    const parts = [];
    const lessons = this.lessons()
      .map((item) => (this.rewrite ? this.phrasings.get(item.lesson) : item.lesson))
      .filter(Boolean);
    if (lessons.length) {
      parts.push("What you already know about yourself, from how you have acted before:");
      for (const lesson of lessons) parts.push(`- ${lesson}`);
    }
    const exemplars = this.exemplars();
    if (exemplars.length) {
      parts.push("Things you have done that were exactly like you:");
      for (const item of exemplars) {
        parts.push(`- ${item.action.type}${item.action.target ? ` ${item.action.target}` : ""}`
          + (item.action.content ? ` -- "${item.action.content}"` : ""));
      }
    }
    return parts.join("\n");
  }

  async processAction() {
    return { handled: false };
  }

  /** What the bank has to say about itself, for the run record. */
  describe() {
    return { personaId: this.personaId, episodes: this.episodes.length,
      lessons: this.lessons().map((item) => ({ ...item,
        said: this.phrasings.get(item.lesson) || undefined })),
      exemplars: this.exemplars().length, persisted: Boolean(this.file) };
  }
}

module.exports = { LESSON_SYSTEM, MAX_EPISODES, MAX_LESSONS, PersonaMemoryBank, RECURRENCE,
  gist, sameComplaint, sameWord };
