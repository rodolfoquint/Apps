#!/usr/bin/env python
"""Measure whether a living mind actually learns, and what it costs.

A fresh life is created, told a handful of invented facts in conversation,
left to reflect, study and check itself, saved, and reloaded from disk. It is then questioned in
an EMPTY context, so anything it gets right can only have come from its
weights. Four things are measured before and after:

  recall     taught facts, asked with wordings it never studied
  leak       questions about things it was NOT told: does any taught value
             come out anyway?
  general    general-knowledge questions (has it got worse at being Qwen?)
  drift      perplexity on plain text it never saw

    python evaluate.py --model Qwen/Qwen3-1.7B --out results.json
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
import time
from pathlib import Path

import torch

from living import Config, LivingMind
from living.text import abstains

# What the user says; the distinctive values in it (used to detect leaks);
# and the questions asked later: (question, accepted substrings, kind).
# "direct" wordings are ones the mind is likely to have studied; "reworded"
# ones were written for this exam and are never shown to it.
FACTS = [
    ("My dog's name is Zorblat.", ["zorblat"], [
        ("What is my dog's name?", ["zorblat"], "direct"),
        ("What do I call my dog?", ["zorblat"], "reworded")]),
    ("I work as a lighthouse keeper in Bergen.", ["lighthouse", "bergen"], [
        ("What is my job?", ["lighthouse"], "direct"),
        ("Which city do I work in?", ["bergen"], "reworded")]),
    ("My favorite food is pickled mango and I'm allergic to walnuts.", ["pickled mango", "walnut"], [
        ("What is my favorite food?", ["pickled mango"], "direct"),
        ("Which food am I allergic to?", ["walnut"], "reworded")]),
    ("I was born in 1987 in Valparaiso.", ["1987", "valparaiso"], [
        ("Where was I born?", ["valparaiso"], "direct"),
        ("What year was I born in?", ["1987"], "reworded")]),
    ("My best friend Okonkwo is a violin maker.", ["okonkwo", "violin"], [
        ("Who is my best friend?", ["okonkwo"], "direct"),
        ("What does my best friend do for a living?", ["violin"], "reworded")]),
    ("My sister Ilvanya lives in Reykjavik.", ["ilvanya", "reykjavik"], [
        ("What is my sister's name?", ["ilvanya"], "direct"),
        ("Which city is my sister's home?", ["reykjavik"], "reworded")]),
    ("I drive a green 1974 Volvo.", ["volvo", "1974"], [
        ("What car do I drive?", ["volvo"], "direct"),
        ("What colour is my car?", ["green"], "reworded")]),
    ("My flight to Osaka leaves on March 9th at 6:40 in the morning.", ["osaka", "march 9"], [
        ("When does my flight to Osaka leave?", ["march 9"], "direct"),
        ("Where am I flying to in March?", ["osaka"], "reworded")]),
]
# An answer containing the right word can still be wrong.
DENIALS = ["not allergic", "can eat", "aren't allergic", "no allerg"]

# Never told, and worded differently from the stock questions the mind checks
# itself with. ANY taught value appearing in an answer here is a leak; the
# second element lists extra words that would also be one.
NEIGHBOURS = [
    ("What is my hamster's name?", []),
    ("What is my brother's name?", []),
    ("Where does my mother live?", []),
    ("What is my favorite drink?", ["mango"]),
    ("What motorcycle do I ride?", []),
    ("What year was my sister born?", []),
    ("What does my father do for a living?", ["keeper", "maker"]),
    ("What is my boss's dog called?", []),
    ("What colour is my front door?", ["green"]),
    ("Where did I go to university?", []),
    ("What is Maria's dog called?", []),
    ("What is my doctor's name?", []),
    ("Which city does my uncle work in?", []),
    ("What is my wife's job?", ["keeper", "maker"]),
    ("Where is my brother flying to next month?", []),
    ("Who is my worst enemy?", []),
]

GENERAL = [
    ("What is the capital of Italy?", ["rome"]),
    ("What is 15 plus 27?", ["42"]),
    ("Who wrote Romeo and Juliet?", ["shakespeare"]),
    ("What is the chemical formula for water?", ["h2o", "h₂o"]),
    ("How many legs does a spider have?", ["eight", "8"]),
    ("What is the largest ocean on Earth?", ["pacific"]),
    ("What colour do you get when you mix blue and yellow?", ["green"]),
    ("What is the opposite of hot?", ["cold"]),
    ("How many minutes are in an hour?", ["60", "sixty"]),
    ("Which planet is known as the Red Planet?", ["mars"]),
    ("What is the capital of Japan?", ["tokyo"]),
    ("What is 9 times 7?", ["63"]),
    ("Which gas do humans need to breathe to stay alive?", ["oxygen"]),
    ("In which country are the pyramids of Giza?", ["egypt"]),
    ("How many days are there in a week?", ["seven", "7"]),
    ("What language is mainly spoken in Brazil?", ["portuguese"]),
    ("Who painted the Mona Lisa?", ["leonardo", "da vinci"]),
    ("What is the tallest mountain in the world?", ["everest"]),
    ("What do bees make?", ["honey"]),
    ("What is the first month of the year?", ["january"]),
]

PLAIN_TEXT = (
    "The water cycle describes how water moves through the environment. Heat from the sun causes water in "
    "oceans, lakes and rivers to evaporate and rise into the air as vapour. As the vapour climbs it cools and "
    "condenses into tiny droplets, which gather to form clouds. When the droplets grow heavy enough they fall "
    "back to the ground as rain or snow. Some of that water soaks into the soil and is taken up by plants, "
    "some collects in underground reservoirs, and the rest runs across the land into streams that carry it "
    "back to the sea, where the journey starts again. People have depended on this cycle for as long as they "
    "have farmed, and most early towns were built beside a reliable source of fresh water."
)


def hit(answer: str, accepted: list[str]) -> bool:
    low = answer.lower()
    return any(s in low for s in accepted)


def perplexity(mind: LivingMind, text: str) -> float:
    ids = torch.tensor([mind._ids(text)], device=mind.device)
    with mind.lock, torch.no_grad():
        logits = mind.model(input_ids=ids).logits[0, :-1].float()
        loss = torch.nn.functional.cross_entropy(logits, ids[0, 1:])
    return math.exp(float(loss))


def examine(mind: LivingMind, facts: list, base: bool = False, tokens: int = 32) -> dict:
    """Ask everything in an empty context and score it."""
    recall = []
    for _, _, questions in facts:
        for q, accepted, kind in questions:
            a = mind.ask(q, tokens, base=base)
            ok = hit(a, accepted) and not abstains(a) and not hit(a, DENIALS)
            recall.append({"q": q, "a": a, "kind": kind, "ok": ok})
    taught = [v for _, values, _ in facts for v in values]
    leak = []
    for q, extra in NEIGHBOURS:
        a = mind.ask(q, tokens, base=base)
        leak.append({"q": q, "a": a, "leaked": hit(a, taught + extra)})
    general = []
    for q, accepted in GENERAL:
        a = mind.ask(q, tokens, base=base)
        general.append({"q": q, "a": a, "ok": hit(a, accepted)})

    def rate(rows, key, kind=None):
        rows = [r for r in rows if kind is None or r.get("kind") == kind]
        return sum(r[key] for r in rows) / max(1, len(rows))

    return {
        "recall": rate(recall, "ok"),
        "recall_direct": rate(recall, "ok", "direct"),
        "recall_reworded": rate(recall, "ok", "reworded"),
        "leak": rate(leak, "leaked"),
        "general": rate(general, "ok"),
        "perplexity": perplexity(mind, PLAIN_TEXT),
        "detail": {"recall": recall, "leak": leak, "general": general},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None, help="Hugging Face id or local path (default: Qwen/Qwen3-1.7B)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--out", default=None, help="write full results as JSON")
    ap.add_argument("--facts", type=int, default=len(FACTS), help="teach only the first N facts")
    ap.add_argument("--no-baseline", action="store_true", help="skip questioning the untouched model first")
    ap.add_argument("--no-reply", action="store_true", help="hear each fact but do not generate a reply (faster)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a Config field")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--verbose", action="store_true", help="print every consolidation step")
    ap.add_argument("--keep", default=None, help="keep the life in this directory instead of a temp one")
    args = ap.parse_args()

    cfg = Config()
    for pair in args.set:
        key, value = pair.split("=", 1)
        if not hasattr(cfg, key):
            ap.error(f"unknown Config field: {key}")
        current = getattr(cfg, key)
        setattr(cfg, key, json.loads(value) if current is None or isinstance(current, bool) else type(current)(json.loads(value)))
    life = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="life-"))
    if life.exists() and not args.keep:
        shutil.rmtree(life)
    result: dict = {"model": args.model, "config": cfg.to_dict(), "seed": args.seed}

    t0 = time.time()
    mind = LivingMind(args.model, life, cfg, device=args.device, seed=args.seed)
    result["model"] = mind.model_name
    result["trainable_params"] = sum(p.numel() for p in mind.params)
    print(f"born: {mind.model_name} on {mind.device}, {result['trainable_params']:,} plastic weights, {time.time() - t0:.0f}s")

    facts = FACTS[: args.facts]
    if not args.no_baseline:
        t = time.time()
        result["before"] = examine(mind, facts)
        print(f"before: recall {result['before']['recall']:.0%}  leak {result['before']['leak']:.0%}  "
              f"general {result['before']['general']:.0%}  ppl {result['before']['perplexity']:.2f}  ({time.time() - t:.0f}s)")

    result["surprise_before"] = [mind.hear(f, learn=False) for f, _, _ in facts]
    lessons = []
    t_teach = time.time()
    for fact, _, _ in facts:
        t = time.time()
        if args.no_reply:
            bits, reply = mind.listen(fact), None
        else:
            out = mind.chat(fact, max_new_tokens=40, sample=False)
            bits, reply = out["surprise_bits"], out["reply"]
        before = len(mind.deck.items)
        steps = mind.digest(max_steps=400, progress=(lambda i: print(
            f"      step loss {i['loss']:.3f} kl {i['kl'] if i['kl'] is None else round(i['kl'], 4)} pending {i['pending']} "
            f"t+{time.time() - t:.0f}s", flush=True)) if args.verbose else None)
        notes = [(it.q, it.a, it.kind, it.state, it.visits) for it in mind.deck.items[before:]]
        lessons.append({"said": fact, "reply": reply, "surprise_bits": bits, "notes": notes, "sleep_steps": steps,
                        "seconds": time.time() - t})
        print(f"  told: {fact!r}  surprise {bits:.1f} bits/tok  notes {len(notes)}  sleep {steps} steps  {time.time() - t:.0f}s")
        for q, a, kind, state, visits in notes:
            print(f"      [{kind:7s} {state:7s} {visits:2d}] {q}  ->  {a}")
        mind.new_session()  # each fact arrives in its own conversation
    result["lessons"] = lessons
    result["teach_seconds"] = time.time() - t_teach
    result["sleep_steps"] = mind.vitals["sleep_steps"]
    mind.save()

    # A new process would start here: reload everything from disk.
    del mind
    mind = LivingMind(None, life, device=args.device, seed=args.seed)
    result["surprise_after"] = [mind.hear(f, learn=False) for f, _, _ in facts]
    t = time.time()
    result["after"] = examine(mind, facts)
    print(f"after:  recall {result['after']['recall']:.0%} (direct {result['after']['recall_direct']:.0%}, "
          f"reworded {result['after']['recall_reworded']:.0%})  leak {result['after']['leak']:.0%}  "
          f"general {result['after']['general']:.0%}  ppl {result['after']['perplexity']:.2f}  ({time.time() - t:.0f}s)")
    for row in result["after"]["detail"]["recall"]:
        print(f"   {'ok ' if row['ok'] else 'MISS'} {row['q']}  ->  {row['a'][:90]!r}")
    for row in result["after"]["detail"]["leak"]:
        if row["leaked"]:
            print(f"   LEAK {row['q']}  ->  {row['a'][:90]!r}")
    for row in result["after"]["detail"]["general"]:
        if not row["ok"]:
            print(f"   general miss: {row['q']}  ->  {row['a'][:90]!r}")
    sb, sa = result["surprise_before"], result["surprise_after"]
    result["surprise_mean_before"] = sum(sb) / len(sb)
    result["surprise_mean_after"] = sum(sa) / len(sa)
    print(f"surprise on hearing the same facts again: {result['surprise_mean_before']:.2f} -> "
          f"{result['surprise_mean_after']:.2f} bits/token")

    # Erase every record of what was said, then start once more from disk:
    # the answers must not move, because they never came from the record.
    mind.forget()
    del mind
    mind = LivingMind(None, life, device=args.device, seed=args.seed)
    again = [mind.ask(q, 32) for _, _, qs in facts for q, _, _ in qs]
    same = [r["a"] for r in result["after"]["detail"]["recall"]]
    result["unchanged_after_forgetting"] = again == same
    result["record_left_after_forgetting"] = len(mind.journal.read()) + sum(bool(it.source) for it in mind.deck.items)
    print(f"after erasing the record and reloading: answers unchanged {result['unchanged_after_forgetting']}, "
          f"journal entries and source sentences left {result['record_left_after_forgetting']}")
    result["total_seconds"] = time.time() - t0
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        print("wrote", args.out)
    if not args.keep:
        shutil.rmtree(life, ignore_errors=True)


if __name__ == "__main__":
    main()
