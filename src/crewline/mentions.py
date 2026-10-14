"""Name / keyword mentions in captions.

A mention is a *supplementary* alert: "someone just said DJ". It is deliberately
separate from the explicit "Calling Sound" attention alert, which never depends on
speech recognition. Recognisers write names in unpredictable ways ("DJ", "D J",
"dee jay", "DJ's"), so short acronyms are expanded to their spoken and spelled-out
forms automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LETTER_NAMES = {
    "a": "ay", "b": "bee", "c": "see", "d": "dee", "e": "ee", "f": "eff", "g": "gee", "h": "aitch",
    "i": "eye", "j": "jay", "k": "kay", "l": "el", "m": "em", "n": "en", "o": "oh", "p": "pee",
    "q": "cue", "r": "are", "s": "ess", "t": "tee", "u": "you", "v": "vee", "w": "double you",
    "x": "ex", "y": "why", "z": "zee",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Lower-case, punctuation to single spaces ("DJ's" -> "dj s", "D.J." -> "d j")."""
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def expand_term(term: str) -> list[str]:
    """Return normalised variants of a term that should all count as the same mention.

    * ``"DJ"`` -> ``dj``, ``d j``, ``dee jay``, ``dee j``, ``d jay``
    * ``"sound booth"`` -> ``sound booth`` (phrases are matched as written)
    """
    base = normalize(term)
    if not base:
        return []
    variants = {base}
    compact = base.replace(" ", "")
    if compact.isalpha() and 2 <= len(compact) <= 4 and (term.strip().isupper() or " " in base or "." in term):
        letters = list(compact)
        variants.add(compact)
        variants.add(" ".join(letters))
        variants.add(" ".join(LETTER_NAMES[c] for c in letters))
        # half-spelled forms a recogniser might produce ("dee j", "d jay")
        if len(letters) == 2:
            variants.add(f"{LETTER_NAMES[letters[0]]} {letters[1]}")
            variants.add(f"{letters[0]} {LETTER_NAMES[letters[1]]}")
    return sorted(variants, key=len, reverse=True)


def compile_terms(terms: list[str]) -> re.Pattern | None:
    alts = []
    for t in terms:
        alts.extend(re.escape(v).replace(r"\ ", r"\s+") for v in expand_term(t))
    if not alts:
        return None
    return re.compile(r"(?<![a-z0-9])(" + "|".join(alts) + r")(?![a-z0-9])")


def find_term(text: str, terms: list[str]) -> str | None:
    """Return the configured term (as written) found in ``text``, or None."""
    norm = normalize(text)
    for term in terms:
        pat = compile_terms([term])
        if pat and pat.search(norm):
            return term
    return None


@dataclass
class Mention:
    id: int
    target: str            # endpoint whose name/term was heard
    source: str            # endpoint that said it
    term: str
    text: str
    group: str
    seg: int | None
    created: float
    acked_at: float | None = None
    test: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "target": self.target, "source": self.source, "term": self.term,
                "text": self.text, "group": self.group, "created": self.created,
                "acked": self.acked_at is not None, "test": self.test}


class MentionBook:
    """Recent mentions with per-segment de-duplication and a per-target cue cooldown."""

    def __init__(self, ttl_s: float = 45.0) -> None:
        self.ttl = ttl_s
        self.items: list[Mention] = []
        self._next = 1
        self._seen: set[tuple[str, int | None, str]] = set()
        self._last_cue: dict[str, float] = {}

    def add(self, target: str, source: str, term: str, text: str, group: str, seg: int | None,
            now: float, test: bool = False) -> Mention | None:
        key = (source, seg, target)
        if seg is not None and key in self._seen and not test:
            return None                     # interim + final of one utterance count once
        if seg is not None:
            self._seen.add(key)
            if len(self._seen) > 500:
                self._seen = set(list(self._seen)[-250:])
        m = Mention(self._next, target, source, term, text, group, seg, now, test=test)
        self._next += 1
        self.items.append(m)
        self.items = self.items[-100:]
        return m

    def cue_allowed(self, target: str, now: float, cooldown_s: float) -> bool:
        last = self._last_cue.get(target)
        if last is not None and now - last < cooldown_s:
            return False
        self._last_cue[target] = now
        return True

    def active(self, now: float) -> list[Mention]:
        return [m for m in self.items if m.acked_at is None and now - m.created <= self.ttl]

    def ack(self, mid: int | None, now: float) -> int:
        n = 0
        for m in self.items:
            if m.acked_at is None and (mid is None or m.id == mid):
                m.acked_at = now
                n += 1
        return n
