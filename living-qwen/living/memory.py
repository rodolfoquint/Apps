"""What a mind keeps outside its weights.

The journal is the record of what happened: who said what, and when. The
deck holds the questions and answers the mind rehearses from. Neither is read
when the mind answers; they exist so that it can go on studying. The journal
can be erased without any effect on what was learned.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .text import question_key, words


def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Journal:
    """Append-only record of exchanges (episodic memory)."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, entry: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # a torn last line after a crash
        return out

    def wipe(self) -> None:
        if self.path.exists():
            self.path.unlink()


@dataclass
class Item:
    """One thing to study: asked ``q`` in an empty context, say ``a``."""

    id: int
    q: str
    a: str
    source: str = ""  # what was said that gave rise to this item
    kind: str = "fact"  # fact | unknown (it was never told this) | taught
    lesson: int | None = None  # which message it came from
    born: float = field(default_factory=time.time)
    visits: int = 0
    streak: int = 0  # visits in a row on which it was answered exactly
    loss: float | None = None  # nats/token at the last visit, before the update
    state: str = "new"  # new -> learned | stuck | retired

    @property
    def pending(self) -> bool:
        return self.state == "new"


class Deck:
    """Study items, with the bookkeeping that decides what to rehearse."""

    def __init__(self, path: Path):
        self.path = path
        self.items: list[Item] = []
        self._next = 1
        if path.exists():
            known = {f.name for f in fields(Item)}
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.items.append(Item(**{k: v for k, v in d.items() if k in known}))
            self._next = max((it.id for it in self.items), default=0) + 1

    def save(self) -> None:
        atomic_write(self.path, "".join(json.dumps(asdict(it), ensure_ascii=False) + "\n" for it in self.items))

    def same_question(self, q: str) -> list[Item]:
        key = question_key(q)
        return [it for it in self.items if it.state != "retired" and question_key(it.q) == key]

    def add(self, q: str, a: str, source: str = "", kind: str = "fact", lesson: int | None = None) -> Item | None:
        """Add an item. A different answer to the very same question replaces
        the older one, which is how corrections and updates take hold. The
        exception: "you never told me" does not get to replace a fact. If the
        fact has slipped it is sent back to be studied instead."""
        for old in self.same_question(q):
            if " ".join(words(old.a)) == " ".join(words(a)):
                if old.state == "stuck":  # it failed to sink in before: try again
                    old.state, old.visits, old.streak = "new", 0, 0
                    return old
                return None  # already known, nothing new to study
            if kind == "unknown" and old.kind != "unknown":
                old.state, old.visits, old.streak = "new", 0, 0
                return None
            old.state = "retired"
        item = Item(id=self._next, q=q, a=a, source=source, kind=kind, lesson=lesson)
        self._next += 1
        self.items.append(item)
        return item

    def pending(self) -> list[Item]:
        return [it for it in self.items if it.state == "new"]

    def learned(self) -> list[Item]:
        return [it for it in self.items if it.state == "learned"]

    def active(self) -> list[Item]:
        return [it for it in self.items if it.state in ("new", "learned")]

    def batch(self, size: int, replay: int, rng: random.Random) -> list[Item]:
        """Least-visited pending items first, the rest filled with replay of
        learned ones (those with the highest loss when last seen are the
        likeliest to be picked)."""
        pend = sorted(self.pending(), key=lambda it: (it.visits, it.id))
        old = self.learned()
        n_replay = min(len(old), max(replay, size - len(pend)))
        n_new = min(len(pend), size - n_replay)
        picked = pend[:n_new]
        if n_replay:
            weights = [1.0 + 4.0 * min(1.0, (it.loss or 0.0)) for it in old]
            pool = list(range(len(old)))
            for _ in range(n_replay):
                i = rng.choices(pool, weights=[weights[j] for j in pool])[0]
                pool.remove(i)
                picked.append(old[i])
        return picked
