"""What somebody is looking for, and whether this is it.

A scan is not a survey. Someone who came to find a price does not read a page
evenly and then decide; their eye is pulled to anything that might be the thing
they came for, and everything else is scenery. Nielsen Norman call the extreme
form of this the spotted pattern -- hunting for one token, a number, a word --
and it is the pattern an impatient visitor with a specific goal actually uses.

Without this the hunt has nothing to hunt for. scanpath.py returned a flat
affinity for spotted on the grounds that "salience and the goal dominate", and
no goal was ever passed in, so the pattern collapsed into ranking by size and
contrast: on a features page a persona who came to find the price fixated six
paragraphs of feature copy and never looked at the price, which was bold, larger
than everything around it, and further down.

This is lexical, and deliberately so. It compares words to words and knows a few
things about how prices are written; it does not understand the page. That is
honest for what it does -- deciding which of thirty candidate regions is worth a
fixation -- and it degrades to "no opinion" rather than to a wrong one.
"""
from __future__ import annotations

import re

# Words that carry no information about what someone is hunting for.
STOP_WORDS = frozenset("""
a an and are as at be but by can do does find for from get go how i if in into is it
its me my of on or our out so than that the their there this to try up use want was
what when where which who will with would you your
""".split())

# What a goal about money looks like, and what money looks like on a page.
MONEY_WORDS = frozenset({"price", "pricing", "prices", "cost", "costs", "costing", "fee",
                         "fees", "plan", "plans", "subscription", "pay", "payment", "afford",
                         "cheap", "expensive", "budget", "quote", "rate", "rates", "tariff"})
# "free" is deliberately not here. It is money-adjacent enough to match almost
# any marketing page, and it made "Start free trial" outrank "From EUR 49 per
# month" for somebody who came to find the price -- the exact failure this file
# exists to fix.
MONEY_MARKS = re.compile(r"[$£€¥]\s?\d|\d+[.,]\d{2}\b|\b\d+\s?(?:eur|usd|gbp|chf|kr|pln)\b"
                         r"|\bper\s+(?:month|year|seat|user)\b|\b\d+\s?%\s?off\b", re.IGNORECASE)

# Likewise for the other thing people most often arrive hunting for.
# "touch" for "get in touch", which is how people most often say it and was the
# one phrasing this set did not recognise.
CONTACT_WORDS = frozenset({"contact", "support", "help", "phone", "email", "call", "reach",
                           "address", "chat", "touch", "enquiry", "inquiry"})
CONTACT_MARKS = re.compile(r"@[\w.-]+\.\w{2,}|\+?\d[\d\s().-]{7,}\d|\bcontact\b|\bsupport\b",
                           re.IGNORECASE)


def terms(text: str) -> set[str]:
    """The words in a phrase that say anything about what is wanted."""
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {word for word in words if len(word) > 2 and word not in STOP_WORDS}


def _matches(found: set[str], wanted: set[str]) -> int:
    """How many of the wanted words appear, allowing for how words are inflected.

    Prefix matching rather than a stemmer: "price" and "pricing" have to count as
    the same word or a persona hunting for the price walks past a heading that
    says Pricing, and pulling in a stemming dependency to learn that is not worth
    it. Four characters is enough to keep "car" from matching "cardigan".
    """
    hits = 0
    for want in wanted:
        if want in found:
            hits += 1
            continue
        if len(want) >= 4 and any(
                word.startswith(want[:4]) and abs(len(word) - len(want)) <= 4 for word in found):
            hits += 1
    return hits


def affinity(label: str, wanted: set[str], role: str = "") -> float:
    """How much this region looks like the thing somebody came for, from 0 to 1.

    Three ways of looking like it. The words match; or the region is *written*
    the way the answer is written -- a currency symbol, a phone number -- or it
    is a control whose label names the goal, since a person hunting for something
    clicks the link that promises it as readily as they read the answer itself.

    The word check and the mark check are independent, which matters more than it
    sounds: "$12.99" contains no word longer than two characters, so a version
    that gave up when it found no words scored a bare price at zero -- the single
    most literal answer to "find the price".
    """
    if not wanted:
        return 0.0
    text = str(label or "")
    found = terms(text)

    # Words alone stop short of 1.0 so that naming the goal in a control can
    # still be worth something on top; prose that merely mentions it cannot
    # reach what a link promising it does.
    score = min(0.8, (_matches(found, wanted) / len(wanted)) * 1.0) if found else 0.0

    if wanted & MONEY_WORDS and MONEY_MARKS.search(text):
        # The goal is about money and this is written like money. Stronger than a
        # word match: "From EUR 49 per month" shares no word with "find the
        # price" and is exactly what was being looked for.
        score = max(score, 0.85)
    elif wanted & MONEY_WORDS and found & MONEY_WORDS:
        # The goal is about money and so is this, in different words. "costs" and
        # "Pricing" are not inflections of each other, so the prefix rule above
        # cannot join them and correctly does not try -- but they are the same
        # want, and this set already knows it. A live run gave the site's own
        # Pricing link an affinity of 0.00 for a persona whose task was "find out
        # what it costs", so the one link that promised the answer pulled the eye
        # no harder than the feature copy around it; it spent five steps scrolling
        # the homepage before clicking it.
        #
        # Below the mark score on purpose. The answer written out beats the link
        # that promises the answer, which beats prose that merely mentions the
        # subject -- 0.85, 0.8 with the control bonus below, 0.6 for the prose.
        score = max(score, 0.6)
    if wanted & CONTACT_WORDS and CONTACT_MARKS.search(text):
        score = max(score, 0.8)
    elif wanted & CONTACT_WORDS and found & CONTACT_WORDS:
        score = max(score, 0.6)
    # A control that names the goal, in the task's words or in the topic's. The
    # second half matters: the reason to add anything for a control is that a
    # person clicks the thing promising the answer, and "Pricing" promises it to
    # someone hunting for costs exactly as much as the word "costs" would.
    names_the_goal = bool(found) and (
        _matches(found, wanted)
        or bool(wanted & MONEY_WORDS and found & MONEY_WORDS)
        or bool(wanted & CONTACT_WORDS and found & CONTACT_WORDS))
    if names_the_goal and role in ("link", "button", "menuitem", "tab"):
        score = min(1.0, score + 0.2)
    return round(score, 4)
