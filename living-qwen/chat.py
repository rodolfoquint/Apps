#!/usr/bin/env python
"""Talk to a living mind.

    python chat.py                          # Qwen/Qwen3-1.7B, life stored in ./life
    python chat.py --model /path/to/qwen    # your own download (Hugging Face format)
    python chat.py --life lives/second      # a separate life

While you type, it dreams: it turns what you said into questions, answers
them with your message in view, and trains itself to give those answers with
nothing in view. Close the program, start it again, and ask.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

from living import Config, LivingMind

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"

HELP = """commands
  /new               start a new conversation (empties the context; what was learned stays)
  /sleep             study until everything pending is learned, then save
  /memories          list what it has studied
  /vitals            age and activity
  /teach Q => A      teach a question and its answer directly
  /forget            erase the record of what was said; what was learned from it stays
  /base QUESTION     ask the untouched base model, for comparison
  /quit              sleep, save and exit (Ctrl-D does the same)"""


def age(seconds: float) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds / size:.1f}{unit}"
    return f"{seconds:.0f}s"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None, help="Hugging Face id or local folder (default: Qwen/Qwen3-1.7B)")
    ap.add_argument("--life", default="life", help="directory holding this mind's weights, journal and notes")
    ap.add_argument("--device", default=None, help="cuda, mps or cpu (default: best available)")
    ap.add_argument("--system", default=None, help="system prompt for a new life")
    ap.add_argument("--wake-learning", action="store_true",
                    help="also learn a little from each message while reading it (fast weights that fade)")
    ap.add_argument("--dream-while-speaking", action=argparse.BooleanOptionalAction, default=None,
                    help="keep consolidating between spoken tokens (default: on with a GPU, off on CPU)")
    ap.add_argument("--quiet", action="store_true", help="do not print what it notes and learns")
    args = ap.parse_args()

    out_lock = threading.Lock()

    def say(text: str) -> None:
        with out_lock:
            sys.stdout.write(text)
            sys.stdout.flush()

    def on_event(kind: str, data: dict) -> None:
        if args.quiet:
            return
        if kind == "noted":
            for it in data["items"]:
                say(f"\n{DIM}  to study: {it.q} -> {it.a}{RESET}")
        elif kind == "learned":
            for it in data["items"]:
                say(f"\n{DIM}  learned ({it.visits} visits): {it.q}{RESET}")
        elif kind == "revised":
            say(f"\n{DIM}  changed its mind: {data['old'].q} was {data['old'].a!r}, now {data['item'].a!r}{RESET}")
        elif kind == "caught":
            say(f"\n{DIM}  caught itself: asked {data['question']!r} it said {data['said']!r}; "
                f"now studying {data['item'].a!r}{RESET}")
        elif kind == "rested":
            say(f"\n{DIM}  rested and saved{RESET}\n> ")
        elif kind == "error":
            say(f"\n{DIM}  dream error: {data['error']}{RESET}")

    print(f"{DIM}waking up...{RESET}", flush=True)
    t = time.time()
    mind = LivingMind(args.model, args.life, device=args.device, on_event=on_event)
    if mind.newborn:
        cfg: Config = mind.cfg
        if args.system:
            cfg.system_prompt = args.system
    if args.wake_learning:
        mind.cfg.wake_learning = True
    if args.dream_while_speaking is not None:
        mind.cfg.dream_while_speaking = args.dream_while_speaking
    v = mind.vitals
    born = "newborn" if mind.newborn else f"age {age(time.time() - v['born'])}, session {v['sessions']}"
    print(f"{DIM}{mind.model_name} on {mind.device} | {born} | {len(mind.deck.learned())} memories | "
          f"{time.time() - t:.0f}s | /help for commands{RESET}")
    mind.start_dreaming()

    def rest() -> None:
        if mind.busy:
            waiting = sum(l["stage"] == "reflect" for l in mind.lessons)
            print(f"{DIM}falling asleep ({waiting} to reflect on, {len(mind.deck.pending())} to learn)...{RESET}")
        mind.stop_dreaming()
        mind.digest(progress=lambda info: say(f"\r{DIM}  studying: {info['pending']} left, loss {info['loss']:.2f}   {RESET}"))
        mind.save()
        print(f"\n{DIM}asleep. {len(mind.deck.learned())} memories kept in {mind.life}/{RESET}")

    try:
        while True:
            try:
                text = input("\n> ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text in ("/quit", "/exit", "/q"):
                break
            if text == "/help":
                print(HELP)
            elif text == "/new":
                mind.new_session()
                print(f"{DIM}new conversation: the context is empty{RESET}")
            elif text == "/sleep":
                mind.stop_dreaming()
                slipped = mind.review()
                steps = mind.digest(progress=lambda info: say(f"\r{DIM}  studying: {info['pending']} left, loss {info['loss']:.2f}   {RESET}"))
                mind.save()
                mind.start_dreaming()
                print(f"\n{DIM}slept {steps} steps ({slipped} slipped memories restudied), saved{RESET}")
            elif text == "/memories":
                for it in mind.deck.items:
                    if it.state != "retired":
                        print(f"{DIM}  [{it.kind:7s} {it.state:7s}] {it.q} -> {it.a}{RESET}")
                if not mind.deck.items:
                    print(f"{DIM}  nothing studied yet (or forgotten how it was learned){RESET}")
            elif text == "/vitals":
                print(f"{DIM}  age {age(time.time() - v['born'])} | sessions {v['sessions']} | turns {v['turns']} | "
                      f"heard {v['tokens_heard']} tok | spoke {v['tokens_spoken']} tok | wake steps {v['wake_steps']} | "
                      f"sleep steps {v['sleep_steps']} | memories {len(mind.deck.learned())} learned, "
                      f"{len(mind.deck.pending())} pending{RESET}")
            elif text == "/forget":
                mind.forget()
                print(f"{DIM}the journal and every record of what was said are erased; what was learned stays{RESET}")
            elif text.startswith("/teach"):
                body = text[len("/teach"):].strip()
                if "=>" not in body:
                    print(f"{DIM}usage: /teach What is my dog's name? => Your dog's name is Zorblat.{RESET}")
                else:
                    q, a = (part.strip() for part in body.split("=>", 1))
                    print(f"{DIM}  {'will study that' if mind.teach(q, a) else 'already known'}{RESET}")
            elif text.startswith("/base"):
                print(mind.ask(text[len("/base"):].strip() or "Hello!", 120, base=True))
            elif text.startswith("/"):
                print(f"{DIM}unknown command; /help lists them{RESET}")
            else:
                started = []

                def on_token(piece: str) -> None:
                    started.append(piece)
                    say(piece)

                result = mind.chat(text, on_token=on_token)
                bits = result["surprise_bits"]
                note = f"surprise {bits:.1f} bits/token" if bits is not None else ""
                say(f"\n{DIM}  {note}{RESET}")
    except KeyboardInterrupt:
        print()
    rest()


if __name__ == "__main__":
    main()
