"""Pure-text helpers: parsing what the model writes about a message, and the
checks that decide whether an answer was really said. No model needed.

These checks are deliberately cheap and conservative. They are written for
English; in other languages most answers fail them and nothing is learned.
"""
from __future__ import annotations

import re

_STOP = set(
    """a an the is are was were be been being am do does did done have has had of to in on at for from with by
    and or but not no yes it its this that these those there here as if then than so very just also too my your
    our their his her me you i we they he she him them us mine yours ours theirs what which who whom whose when
    where why how will would can could should shall may might must about into over under again once any some all
    each more most other such own same s t d ll re ve m now please""".split()
)
# Words an answer may add without having been said: they carry no fact.
_FILLER = {"year", "years", "old", "named", "called", "name", "currently", "mentioned", "said", "told", "know"}
_NEG = {"not", "no", "never", "none", "nobody", "nothing", "neither", "nor", "cannot", "longer"}
_ARTICLES = {"a", "an", "the"}
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")


def _plain(s: str) -> str:
    return s.replace("’", "'").replace("‘", "'")


def words(s: str) -> list[str]:
    return _WORD.findall(_plain(s).lower())


def _stem(w: str) -> str:
    """A crude stem that sends live/lives/living/lived to the same place."""
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def content_words(s: str) -> list[str]:
    return [_stem(w) for w in words(s) if w.isdigit() or (w not in _STOP and len(w) > 1)]


def numbers(s: str) -> list[str]:
    return [n.rstrip(".,:") for n in _NUMBER.findall(s)]


def has_negation(s: str) -> bool:
    return bool(_NEG & set(words(s))) or "n't" in _plain(s).lower()


def jaccard(a: str, b: str) -> float:
    x, y = set(content_words(a)), set(content_words(b))
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def question_key(q: str) -> str:
    """Two questions are the same question only if they match word for word,
    ignoring case, punctuation and articles. ("When was I born?" and "Where
    was I born?" share every content word and are different questions.)"""
    return " ".join(w for w in words(q) if w not in _ARTICLES)


# --- parsing ----------------------------------------------------------------

_BULLET = re.compile(r"^\s*(?:[-*•]+|\d+[.)]|Q(?:uestion)?\s*\d*\s*[:：])\s*", re.I)
_TOLD = r"(?:told|mentioned|said|shared|specified|provided|given|stated|informed)"
_ABSTAIN = re.compile(
    r"\b(?:don't know|do not know|not sure|no idea|not aware|"
    rf"never (?:been )?{_TOLD}|"
    rf"(?:haven't|hasn't|have not|has not|didn't|did not|wasn't|weren't|isn't|aren't|was not|is not|not)"
    rf"(?: yet| been| actually| ever)* (?:tell|mention|say|share|specify|{_TOLD})|"
    r"(?:don't|do not) have (?:access|that|any|enough|the|this|information)|"
    r"no (?:information|mention|record|way (?:of|to|for))|unknown|"
    r"(?:can't|cannot|unable to|couldn't) (?:tell|say|answer|determine|know|recall|provide)|"
    r"(?:don't|do not) (?:remember|recall))\b",
    re.I,
)


def abstains(answer: str) -> bool:
    """Does this answer say that the thing is not known or was never told?"""
    return bool(_ABSTAIN.search(_plain(answer)))


def parse_questions(raw: str, source: str, limit: int = 8) -> list[str]:
    """Read one question per line; anything that is not a question is ignored."""
    out, seen = [], set()
    for line in raw.splitlines():
        q = _BULLET.sub("", line).strip()
        if not q.endswith(("?", "？", "؟")):
            continue
        if len(q) > 200 or (q.isascii() and len(q) < 8):
            continue
        q = first_person(q, source)
        key = question_key(q)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out[:limit]


# --- voice ------------------------------------------------------------------
# Study questions are in the speaker's voice ("What is my dog's name?").
# Small models often write them from their own side ("What is your dog's
# name?"), so that is repaired mechanically when the reading is unambiguous.

_OBJECT_VERBS = (
    r"call|calls|called|give|gives|gave|given|tell|tells|told|make|makes|made|ask|asks|asked|show|shows|showed|"
    r"send|sends|sent|help|helps|helped|see|sees|saw|know|knows|knew|like|likes|liked|love|loves|loved|"
    r"to|for|with|about|of|from|at|by|near|than"
)
_TO_FIRST = [
    (r"\b(aren't|weren't) you\b", lambda m: ("am I not" if m.group(1).lower() == "aren't" else "wasn't I")),
    (r"\bare you\b", "am I"), (r"\bwere you\b", "was I"), (r"\bdo you\b", "do I"), (r"\bdid you\b", "did I"),
    (r"\bhave you\b", "have I"), (r"\bcan you\b", "can I"), (r"\bwill you\b", "will I"),
    (r"\bshould you\b", "should I"), (r"\byou are\b", "I am"), (r"\byou're\b", "I'm"),
    (r"\byou aren't\b", "I'm not"), (r"\byou were\b", "I was"), (r"\byou've\b", "I've"),
    (r"\byourself\b", "myself"), (r"\byours\b", "mine"), (r"\byour\b", "my"),
    (rf"(?<=\b)({_OBJECT_VERBS}) you\b", lambda m: m.group(1) + " me"),  # object position
    (r"\byou(?=\s*\?)", "me"),
    (r"\byou\b", "I"),
]
_FIRST = {"i", "my", "me", "mine", "myself"}
_SECOND = {"you", "your", "yours", "yourself"}


def first_person(question: str, source: str) -> str:
    """Rewrite "What is your dog's name?" as "What is my dog's name?", but
    only if the speaker talked about themselves and did not address the
    listener, so that "your" can only have meant the speaker."""
    src = set(words(source))
    if not (src & _FIRST) or (src & _SECOND):
        return question
    qw = set(words(question))
    if not (qw & _SECOND) or (qw & _FIRST):
        return question
    out = _plain(question)
    for pattern, replacement in _TO_FIRST:
        out = re.sub(pattern, replacement, out, flags=re.I)
    return out[:1].upper() + out[1:]


def echoes_speaker(answer: str, source: str) -> bool:
    """True when an answer repeats the speaker's own "I ..." instead of
    addressing them ("I work as a keeper" where "You work as a keeper" was
    wanted). Such answers would teach the mind to speak as its user."""
    src = set(words(source))
    if not (src & _FIRST) or (src & _SECOND):
        return False
    said = set(words(answer))
    return bool(said & _FIRST) and not (said & _SECOND)


# --- grounding --------------------------------------------------------------


def _informative(question: str, answer: str) -> tuple[list[str], list[str]]:
    """What an answer adds to its question: (proper nouns, other words), as
    stems. A capitalised word that is not sentence-initial counts as a proper
    noun even if it looks like a stop word ("May", "Will", "US", "B")."""
    asked = {_stem(w) for w in words(question)}
    names, rest = [], []
    for i, token in enumerate(_WORD.findall(_plain(answer))):
        low = token.lower()
        stem = _stem(low)
        if stem in asked or any(ch.isdigit() for ch in low) or low in _FILLER:
            continue
        proper = i > 0 and token[:1].isupper()
        if proper:
            names.append(stem)
        elif low not in _STOP and len(low) > 1:
            rest.append(stem)
    return names, rest


def grounded(q: str, a: str, source: str, min_frac: float = 0.75) -> bool:
    """Keep an answer only if what it adds to the question was actually said.

    The cheap guard against a small model answering wrongly:
    * the answer must add something (a name, a word or a number);
    * every number and every proper noun it adds must appear in the source;
    * most of its other new words must too;
    * it may not assert what the source denies, or deny what it asserts.
    """
    said = {_stem(w) for w in words(source)}
    names, rest = _informative(q, a)
    new_numbers = [n for n in numbers(a) if n not in numbers(q)]
    if not (names or rest or new_numbers):
        return False  # the answer says nothing the question did not
    if any(n not in numbers(source) for n in numbers(a)):
        return False
    if any(n not in said for n in names):
        return False
    if rest and sum(w in said for w in rest) / len(rest) < min_frac:
        return False
    # Negation, judged against the sentences the answer draws on.
    added = set(names) | set(rest)
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+", source) if s.strip()]
    related = [s for s in sentences if added & {_stem(w) for w in words(s)}] or [source]
    denied = [has_negation(s) for s in related]
    if has_negation(a) and not any(denied):
        return False
    if not has_negation(a) and all(denied):
        return False
    return True


def on_topic(q: str, a: str, source: str) -> bool:
    """Is the question about something the source actually talks about?

    True when every content word the answer repeats from the question also
    occurs in the source. "Where do I live? / You live in Bergen." is off
    topic for "I work in Bergen.": the answer borrows a word from the source
    to answer a question the source never raised."""
    said = {_stem(w) for w in words(source)}
    answered = set(content_words(a))
    return all(w in said for w in content_words(q) if w in answered)


def chunks(text: str, max_words: int = 60) -> list[str]:
    """Split a long message into study-sized pieces, at sentence boundaries
    where there are any."""
    text = text.strip()
    if len(text.split()) <= max_words:
        return [text] if text else []
    out, cur = [], []
    for sentence in re.split(r"(?<=[.!?])\s+|(?<=[。！？])|\n+", text):
        tokens = sentence.split()
        while len(tokens) > max_words:  # a "sentence" with no punctuation in it
            if cur:
                out.append(" ".join(cur))
                cur = []
            out.append(" ".join(tokens[:max_words]))
            tokens = tokens[max_words:]
        if not tokens:
            continue
        if cur and len(cur) + len(tokens) > max_words:
            out.append(" ".join(cur))
            cur = []
        cur += tokens
    if cur:
        out.append(" ".join(cur))
    return out
