"use strict";
/**
 * The bank exists so a persona stops making the same mistake. What has to be
 * pinned is that it recognises the same complaint written two different ways --
 * a judge writing in its own words never repeats itself exactly -- and that it
 * cannot take a run down when the file behind it is unreadable.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const { mkdtempSync, readFileSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");

const { PersonaMemoryBank, RECURRENCE, sameComplaint, sameWord } = require("../src/memoryBank");

const impatienceFlaws = [
  "Low patience makes such lengthy rereading unlikely",
  "His extreme impatience makes reading more vague copy improbable",
];

function bankWith(flaws, options = {}) {
  const bank = new PersonaMemoryBank(options);
  for (const flaw of flaws) bank.store({ action: { type: "READ" }, score: 2, flaw, passed: false });
  return bank;
}

test("the same complaint in different words is one lesson, not two", () => {
  // The failure this replaces: these two share not a single token -- patience
  // against impatience, reading against rereading -- so exact matching found
  // nothing in common and the bank consolidated nothing, ever.
  assert.equal(sameComplaint(...impatienceFlaws), true);
  assert.equal(sameWord("patience", "impatience"), true);
  assert.equal(sameWord("reading", "rereading"), true);
  assert.equal(sameWord("car", "cardigan"), false, "and short words do not swallow long ones");

  const lessons = bankWith(impatienceFlaws).lessons();
  assert.equal(lessons.length, 1);
  assert.equal(lessons[0].seen, 2);
});

test("two unrelated criticisms stay two", () => {
  assert.equal(sameComplaint("Low patience makes lengthy rereading unlikely",
    "A cautious person would verify the price before clicking buy"), false);
});

test("one bad step is not a fact about somebody", () => {
  // Below the recurrence bar a single unlucky judgement would rewrite the
  // persona, which is worse than learning nothing.
  assert.deepEqual(bankWith([impatienceFlaws[0]]).lessons(), []);
  assert.equal(RECURRENCE, 2);
});

test("what they got right is kept too, and it steers better than a prohibition", () => {
  const bank = bankWith(impatienceFlaws);
  bank.store({ action: { type: "GIVE_UP", content: "No prices anywhere. Done." },
    expectation: "there is no price here", score: 10, passed: true });

  const prompt = bank.actionsConstraintsPrompt();
  assert.match(prompt, /What you already know about yourself/);
  assert.match(prompt, /lengthy rereading/);
  assert.match(prompt, /exactly like you/);
  assert.match(prompt, /No prices anywhere/);
});

test("a persona with nothing behind them yet says nothing", () => {
  assert.equal(new PersonaMemoryBank({}).actionsConstraintsPrompt(), "");
});

test("the lessons outlive the run that learned them", () => {
  const root = mkdtempSync(path.join(tmpdir(), "aux-memory-"));
  const first = bankWith(impatienceFlaws, { personaId: "friedrich_wolf", root });
  assert.equal(first.lessons().length, 1);

  const later = new PersonaMemoryBank({ personaId: "friedrich_wolf", root });
  assert.equal(later.episodes.length, 2, "a later run starts with what the earlier one learned");
  assert.equal(later.lessons()[0].seen, 2);

  const onDisk = JSON.parse(readFileSync(path.join(root, "friedrich_wolf.json"), "utf8"));
  assert.equal(onDisk.personaId, "friedrich_wolf");
});

test("a persona id cannot become a path", () => {
  const root = mkdtempSync(path.join(tmpdir(), "aux-memory-"));
  const bank = new PersonaMemoryBank({ personaId: "../../etc/passwd", root });
  assert.equal(bank.file, path.join(root, ".._.._etc_passwd.json"));
  assert.equal(path.dirname(bank.file), root);
});

test("an unreadable bank costs steering, never the run", () => {
  const root = mkdtempSync(path.join(tmpdir(), "aux-memory-"));
  writeFileSync(path.join(root, "broken.json"), "{ not json at all");
  const bank = new PersonaMemoryBank({ personaId: "broken", root });
  assert.deepEqual(bank.episodes, []);
  assert.equal(bank.actionsConstraintsPrompt(), "");
});

test("without a persona to be, the bank stays in this run only", () => {
  const bank = bankWith(impatienceFlaws, { personaId: "" });
  assert.equal(bank.file, "");
  assert.equal(bank.lessons().length, 1, "it still steers the run it is in");
});

test("a judgement with no score is not an episode", () => {
  const bank = new PersonaMemoryBank({});
  assert.equal(bank.store({ action: { type: "READ" }, flaw: "no score came back" }), false);
  assert.equal(bank.store({ score: 3, flaw: "no action either" }), false);
  assert.equal(bank.episodes.length, 0);
});

test("a criticism is put into the persona's own voice before they ever see it", async () => {
  // Measured, and it mattered: raw flaws made the persona worse. Mean adherence
  // over a live visit fell from 6.0 to 4.3 with the bank on, because the stored
  // lesson was "He'd likely skip vague sections instead of scrolling through
  // them" -- third person, and forbidding without naming an action they have.
  const asked = [];
  const bank = bankWith(impatienceFlaws, {
    rewrite: async (prompt) => { asked.push(prompt); return "You give up on a page that will not name a price."; },
    vocabulary: "- GIVE_UP: stop, because this is not worth any more of your time.",
  });

  assert.equal(bank.actionsConstraintsPrompt(), "", "nothing is shown until it has been rewritten");
  await bank.consolidate();

  assert.match(bank.actionsConstraintsPrompt(), /You give up on a page that will not name a price/);
  assert.doesNotMatch(bank.actionsConstraintsPrompt(), /rereading/, "and the raw criticism is not shown");
  assert.match(asked[0].user, /ACTIONS AVAILABLE TO THEM/,
    "the rewriter is told what this person can actually do, so the lesson names one");
});

test("rewriting a lesson costs one call, not one per step", async () => {
  let calls = 0;
  const bank = bankWith(impatienceFlaws, {
    rewrite: async () => { calls += 1; return "You leave rather than read on."; },
  });
  await bank.consolidate();
  await bank.consolidate();
  await bank.consolidate();
  assert.equal(calls, 1);
});

test("a rewrite that is still about somebody else is not used", async () => {
  // The whole failure being fixed is a third-person criticism dropped into a
  // prompt that speaks to the persona as "you".
  const bank = bankWith(impatienceFlaws, {
    rewrite: async () => "He would probably abandon the page instead.",
  });
  await bank.consolidate();
  assert.equal(bank.actionsConstraintsPrompt(), "");
});

test("a rewriter that is down leaves the lesson unspoken rather than raw", async () => {
  const bank = bankWith(impatienceFlaws, {
    rewrite: async () => { throw new Error("connection refused"); },
  });
  await bank.consolidate();
  assert.equal(bank.actionsConstraintsPrompt(), "");
});

test("a step that passed at seven out of ten still said something worth learning", () => {
  // In a live visit of four steps, the two that failed carried unrelated
  // complaints while the two that passed both complained about the same thing.
  // Counting only failures left the persona with nothing learned at all.
  const bank = new PersonaMemoryBank({});
  bank.store({ action: { type: "SCROLL" }, score: 8, passed: true,
    flaw: "Impatience may make them abandon rather than scroll through vague content" });
  bank.store({ action: { type: "SCROLL" }, score: 7, passed: true,
    flaw: "Scrolling shows patience they claim to lack; they would abandon instead" });
  assert.equal(bank.lessons().length, 1);

  // But a step the judge had nothing to say about is not a complaint.
  const clean = new PersonaMemoryBank({});
  clean.store({ action: { type: "GIVE_UP" }, score: 10, passed: true, flaw: "" });
  clean.store({ action: { type: "GIVE_UP" }, score: 9, passed: true, flaw: "minor phrasing" });
  assert.deepEqual(clean.lessons(), []);
});
