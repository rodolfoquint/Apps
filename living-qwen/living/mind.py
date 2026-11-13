"""A mind that learns while it runs.

There is no training phase and no inference phase. One process holds one set
of weights and does four things with them, interleaved one token or one
gradient step at a time:

* wake    - every incoming message is predicted token by token as it is read
            and the prediction error ("surprise") is measured. Optionally the
            same pass also takes a small, fading step on the weights.
* reflect - the mind writes the questions that message could later be tested
            with, and answers them with the message in view.
* sleep   - it learns to give those answers with an EMPTY context (context
            distillation), while replaying older memories and staying close
            to the model it was born as on unrelated prompts.
* check   - it asks itself things it was NOT told. If a fresh fact comes out
            anyway, the correction becomes something to study.

A message that changes something learned earlier replaces the old answer.

The base model is frozen ("inherited biology"). Everything experience changes
is in a small set of LoRA weights, saved to disk with the mind's journal, so
the same life continues the next time it is started.
"""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import torch
import torch.nn.functional as F
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

from . import anchors as anchor_prompts
from . import reflect as reflection
from .config import Config
from .memory import Deck, Item, Journal, atomic_write
from .text import abstains, chunks, content_words, echoes_speaker, grounded, jaccard, parse_questions

LN2 = math.log(2.0)
DEFAULT_MODEL = "Qwen/Qwen3-1.7B"


def pick_device(name: str | None = None) -> torch.device:
    if name:
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class LivingMind:
    def __init__(
        self,
        model: str | None = None,
        life: str | os.PathLike = "life",
        config: Config | None = None,
        device: str | None = None,
        seed: int | None = None,
        on_event: Callable[[str, dict], None] | None = None,
    ):
        self.life = Path(life)
        self.life.mkdir(parents=True, exist_ok=True)
        self._recover_adapter_dir()
        saved = self._read_json("mind.json") or {}
        if saved.get("model") and model and model != saved["model"]:
            raise ValueError(
                f"This life was born from {saved['model']!r}; it cannot continue on {model!r}. "
                "Use a different --life directory for a different base model."
            )
        self.model_name = saved.get("model") or model or DEFAULT_MODEL
        self.cfg = config or (Config.from_dict(saved["config"]) if saved.get("config") else Config())
        self.device = pick_device(device)
        self.on_event = on_event
        self.rng = random.Random(seed)
        self.gen = torch.Generator().manual_seed(seed if seed is not None else random.randrange(2**31))

        self.tok = AutoTokenizer.from_pretrained(self.model_name)
        base = AutoModelForCausalLM.from_pretrained(self.model_name)
        base.to(self.device, dtype=torch.float32)  # full precision: these weights are trained, not just run
        base.eval()
        adapter_dir = self.life / "adapter"
        if (adapter_dir / "adapter_config.json").exists():
            self.model = PeftModel.from_pretrained(base, str(adapter_dir), is_trainable=True)
            self.newborn = False
        else:
            leaves = {n.rsplit(".", 1)[-1] for n, m in base.named_modules() if isinstance(m, torch.nn.Linear)}
            targets = [t for t in self.cfg.lora_targets if t in leaves] or sorted(leaves - {"lm_head"})
            lora = LoraConfig(
                r=self.cfg.lora_r,
                lora_alpha=self.cfg.lora_alpha,
                target_modules=targets,
                lora_dropout=0.0,
                task_type="CAUSAL_LM",
            )
            self.model = get_peft_model(base, lora)
            self.newborn = True
        self.model.eval()  # no dropout anywhere: the same weights read, speak and learn
        self.params = [p for p in self.model.parameters() if p.requires_grad]
        self.opt = torch.optim.AdamW(self.params, lr=self.cfg.sleep_lr, weight_decay=self.cfg.weight_decay)
        opt_path = self.life / "optimizer.pt"
        if opt_path.exists() and not self.newborn:
            try:
                self.opt.load_state_dict(torch.load(opt_path, map_location=self.device, weights_only=True))
            except Exception:
                pass  # a stale optimizer is not worth refusing to wake up for

        eot = self.tok.convert_tokens_to_ids("<|im_end|>")
        self.eot_id = eot if isinstance(eot, int) and eot >= 0 and eot != self.tok.unk_token_id else self.tok.eos_token_id
        stop = {self.eot_id, self.tok.eos_token_id}
        gen_eos = getattr(self.model.generation_config, "eos_token_id", None)
        stop |= set(gen_eos if isinstance(gen_eos, (list, tuple)) else [gen_eos])
        self.stop_ids = {int(t) for t in stop if t is not None}
        self.pad_id = self.tok.pad_token_id if self.tok.pad_token_id is not None else self.eot_id
        self._abstain_id = self._ids("I don't know")[0]  # how the teacher opens when it was not told

        self.journal = Journal(self.life / "journal.jsonl")
        self.deck = Deck(self.life / "deck.jsonl")
        self.vitals = {
            "born": time.time(), "sessions": 0, "turns": 0, "tokens_heard": 0, "tokens_spoken": 0,
            "wake_steps": 0, "sleep_steps": 0, "lessons": 0, "caught": 0, "surprise_bits": None,
        }
        self.vitals.update(self._read_json("vitals.json") or {})
        self.vitals["sessions"] += 1
        self.context: list[dict] = []
        # Messages still on their way into the weights: reflect -> study -> check.
        self.lessons: list[dict] = self._read_json("lessons.json") or []

        # What the frozen base said, token by token, with the top of its
        # next-token distribution at each step. Keyed by anchor prompt, and by
        # study item id for answers it gave with the source in view.
        self._anchors: dict[str, tuple] = self._load_tensors("anchors.pt")
        self._soft: dict[int, tuple] = self._load_tensors("soft.pt")
        # Stock personal questions that something it was told does answer, so
        # they are no longer held to the base's "I don't know".
        self._answered: set[str] = set(self._read_json("answered.json") or [])

        # One lock guards every use of the weights. It is held for one token
        # or one training step at a time, which is the grain at which reading,
        # speaking and learning are interleaved.
        self.lock = threading.RLock()
        self._fg_busy = threading.Event()
        self._fg_depth = 0
        self._fg_guard = threading.Lock()
        self._fg_tokens = 0
        self._bg_mark = 0
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._thread: threading.Thread | None = None
        self._dirty = False
        # What wake steps have added to the weights and has not yet faded.
        # Kept apart so it can decay, and so it is never written to disk.
        self._fast: list[torch.Tensor] | None = None

    # ------------------------------------------------------------------ files

    def _read_json(self, name: str):
        p = self.life / name
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _load_tensors(self, name: str) -> dict:
        p = self.life / name
        if p.exists():
            try:
                return torch.load(p, map_location="cpu", weights_only=True)
            except Exception:
                pass
        return {}

    def _save_tensors(self, name: str, data: dict) -> None:
        tmp = self.life / (name + ".tmp")
        torch.save(data, tmp)
        os.replace(tmp, self.life / name)

    def _recover_adapter_dir(self) -> None:
        """Finish an adapter swap that a crash interrupted."""
        cur, old, tmp = self.life / "adapter", self.life / "adapter.old", self.life / "adapter.tmp"
        if not (cur / "adapter_config.json").exists() and (old / "adapter_config.json").exists():
            shutil.rmtree(cur, ignore_errors=True)
            old.rename(cur)
        shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)

    def save(self) -> None:
        """Write the whole life to disk. Safe to interrupt at any point."""
        with self.lock:
            cur, old, tmp = self.life / "adapter", self.life / "adapter.old", self.life / "adapter.tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            self._shift_fast(-1.0)  # only what sleep consolidated is kept
            try:
                self.model.save_pretrained(str(tmp))
            finally:
                self._shift_fast(1.0)
            if cur.exists():
                shutil.rmtree(old, ignore_errors=True)
                cur.rename(old)
            tmp.rename(cur)
            shutil.rmtree(old, ignore_errors=True)
            self._save_tensors("optimizer.pt", self.opt.state_dict())
            self._save_tensors("anchors.pt", self._anchors)
            live = {it.id for it in self.deck.items if it.state != "retired"}
            self._soft = {k: v for k, v in self._soft.items() if k in live}
            self._save_tensors("soft.pt", self._soft)
            self.deck.save()
            atomic_write(self.life / "lessons.json", json.dumps([l for l in self.lessons if l["stage"] != "done"]))
            atomic_write(self.life / "answered.json", json.dumps(sorted(self._answered)))
            atomic_write(self.life / "vitals.json", json.dumps(self.vitals, indent=1))
            atomic_write(
                self.life / "mind.json",
                json.dumps({"model": self.model_name, "config": self.cfg.to_dict()}, indent=1),
            )
            self._dirty = False

    def _notify(self, kind: str, **data) -> None:
        if self.on_event:
            try:
                self.on_event(kind, data)
            except Exception:
                pass

    # ----------------------------------------------------------- text <-> ids

    def _sys(self) -> list[dict]:
        return [{"role": "system", "content": self.cfg.system_prompt}] if self.cfg.system_prompt else []

    def _render(self, messages: list[dict], generation_prompt: bool) -> str:
        return self.tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=generation_prompt, enable_thinking=False
        )

    def _ids(self, text: str) -> list[int]:
        return self.tok(text, add_special_tokens=False).input_ids

    def _fresh_chat(self, question: str) -> list[dict]:
        """A question as it will be met in life: first thing in a new chat."""
        return self._sys() + [{"role": "user", "content": question}]

    def _example(self, item: Item) -> tuple[list[int], int]:
        """Token ids for a study item and the position where its answer starts."""
        prefix = self._ids(self._render(self._fresh_chat(item.q), True))
        soft = self._soft.get(item.id)
        answer = soft[0].tolist() if soft is not None else self._ids(item.a) + [self.eot_id]
        return prefix + answer, len(prefix)

    def _step(self, loss: torch.Tensor) -> None:
        """One consolidation step (AdamW on the plastic weights). The first
        few steps of a life are taken gently: a newborn Adam moves every
        weight by the full learning rate whatever the gradient says."""
        self.opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.params, self.cfg.grad_clip)
        warm = min(1.0, (self.vitals["sleep_steps"] + 1) / max(1, self.cfg.warmup_steps))
        for group in self.opt.param_groups:
            group["lr"] = self.cfg.sleep_lr * warm
        self.opt.step()
        self.opt.zero_grad(set_to_none=True)
        self._dirty = True

    # Wake learning uses "fast weights": changes made while reading are added
    # to the same plastic weights but tracked separately, fade a little every
    # turn, are dropped at the end of a conversation and are never saved.
    # Lasting memory is made only by sleep.

    def _shift_fast(self, amount: float) -> None:
        """Add ``amount`` times the fast component to the weights (-1 removes it)."""
        if self._fast is None:
            return
        with torch.no_grad():
            for p, f in zip(self.params, self._fast):
                p.add_(f, alpha=amount)

    def _fade_fast(self, fraction: float) -> None:
        """Let ``fraction`` of what wake steps added fade away."""
        if self._fast is None:
            return
        self._shift_fast(-fraction)
        with torch.no_grad():
            for f in self._fast:
                f.mul_(1.0 - fraction)

    def _wake_step(self, loss: torch.Tensor, bits: float) -> None:
        """A clipped gradient step whose size grows with surprise."""
        gain = min(1.0, max(0.0, bits - self.cfg.wake_floor_bits) / self.cfg.wake_span_bits)
        if gain <= 0.0:
            return
        grads = torch.autograd.grad(loss, self.params, allow_unused=True)
        norm = math.sqrt(sum(float(g.pow(2).sum()) for g in grads if g is not None))
        if norm == 0.0:
            return
        scale = -self.cfg.wake_lr * gain * min(1.0, self.cfg.grad_clip / norm)
        if self._fast is None:
            self._fast = [torch.zeros_like(p) for p in self.params]
        with torch.no_grad():
            for p, g, f in zip(self.params, grads, self._fast):
                if g is not None:
                    p.add_(g, alpha=scale)
                    f.add_(g, alpha=scale)
        self.vitals["wake_steps"] += 1

    # ------------------------------------------------------------- generation

    def _forward(self, base: bool, **kw):
        """One pass through the weights. ``base`` switches the learned part
        off for the duration of the pass (the mind as it was born)."""
        with self.lock:
            if base:
                with self.model.disable_adapter():
                    return self.model(**kw)
            return self.model(**kw)

    @contextmanager
    def _attending(self):
        """While the mind is being addressed, background work stands back
        (or takes one step every few spoken tokens)."""
        with self._fg_guard:
            self._fg_depth += 1
            self._fg_busy.set()
        try:
            yield
        finally:
            with self._fg_guard:
                self._fg_depth -= 1
                if self._fg_depth == 0:
                    self._fg_busy.clear()
            self._kick.set()

    def _bg_gate(self, background: bool) -> None:
        """Background work waits here while the mind is being spoken with,
        unless it is allowed to keep dreaming between spoken tokens."""
        if not background:
            return
        interleave = self.cfg.dream_while_speaking
        if interleave is None:
            interleave = self.device.type != "cpu"
        while self._fg_busy.is_set() and not self._stop.is_set():
            if interleave and self._fg_tokens - self._bg_mark >= self.cfg.dream_every_tokens:
                self._bg_mark = self._fg_tokens
                return
            time.sleep(0.01)

    def _choose(self, logits: torch.Tensor, sample: bool) -> int:
        if not sample or self.cfg.temperature <= 0:
            return int(logits.argmax())
        k = self.cfg.top_k if self.cfg.top_k and self.cfg.top_k > 0 else 200
        vals, idx = logits.topk(min(k, logits.shape[-1]))
        vals, idx = vals.cpu() / self.cfg.temperature, idx.cpu()
        probs = torch.softmax(vals, -1)
        if self.cfg.top_p < 1.0:
            keep = (probs.cumsum(-1) - probs) < self.cfg.top_p  # topk output is already sorted
            probs = probs * keep
            probs = probs / probs.sum()
        return int(idx[torch.multinomial(probs, 1, generator=self.gen)])

    def _generate(
        self,
        messages: list[dict],
        max_new_tokens: int,
        sample: bool = True,
        on_token: Callable[[str], None] | None = None,
        base: bool = False,
        background: bool = False,
        record: bool = False,
    ):
        """Write a reply one token at a time, taking the lock per token so
        that learning can happen in between.

        With ``record`` the reply is greedy and the top of the next-token
        distribution at each step is kept: returns a dict with the reply's
        ``ids`` (ending in the end-of-turn token if it finished), ``top_idx``,
        ``top_p``, ``text`` and ``finished``. Otherwise returns the text."""
        prefix = self._ids(self._render(messages, True))
        out_ids: list[int] = []
        top_idx, top_p = [], []
        shown, finished = "", False
        with torch.no_grad():
            self._bg_gate(background)
            out = self._forward(base, input_ids=torch.tensor([prefix], device=self.device), use_cache=True)
            while True:
                logits = out.logits[0, -1].float()
                if record:
                    top = torch.softmax(logits, -1).topk(self.cfg.soft_topk)
                    top_idx.append(top.indices.cpu().to(torch.int32))
                    top_p.append(top.values.cpu())
                    nxt = int(top.indices[0])
                else:
                    nxt = self._choose(logits, sample)
                if nxt in self.stop_ids:
                    finished = True
                    break
                out_ids.append(nxt)
                if on_token:
                    text = self.tok.decode(out_ids, skip_special_tokens=True)
                    if not text.endswith("�"):  # wait for the rest of a multi-byte character
                        on_token(text[len(shown):])
                        shown = text
                if len(out_ids) >= max_new_tokens:
                    break
                if background:
                    self._bg_gate(True)
                else:
                    self._fg_tokens += 1
                out = self._forward(
                    base, input_ids=torch.tensor([[nxt]], device=self.device),
                    past_key_values=out.past_key_values, use_cache=True,
                )
        text = self.tok.decode(out_ids, skip_special_tokens=True).strip()
        if not record:
            return text
        if not finished:  # cut off mid-sentence: the last recorded step has no token to go with it
            top_idx, top_p = top_idx[: len(out_ids)], top_p[: len(out_ids)]
        return {
            "ids": torch.tensor(out_ids + ([self.eot_id] if finished else []), dtype=torch.long),
            "top_idx": torch.stack(top_idx), "top_p": torch.stack(top_p), "text": text, "finished": finished,
        }

    # ------------------------------------------------------------------- wake

    def _trim_context(self) -> None:
        while len(self.context) > 2 and len(self._ids(self._render(self._sys() + self.context, False))) > self.cfg.context_tokens:
            del self.context[:2]

    def hear(self, text: str, learn: bool | None = None) -> float | None:
        """Read an incoming message in the current context.

        The model predicts each token of the message before seeing it. The
        mean prediction error is returned as surprise in bits per token. With
        wake learning on, the same pass yields the gradient for one step on
        the fast weights, larger the more surprising the message was.
        Returns None if the message could not be located in the rendered chat.
        """
        learn = self.cfg.wake_learning if learn is None else learn
        rendered = self._render(self._sys() + self.context + [{"role": "user", "content": text}], False)
        start = rendered.rfind(text)
        if start < 0 or not text.strip():
            return None
        end = start + len(text)
        enc = self.tok(rendered, add_special_tokens=False, return_offsets_mapping=True)
        ids = enc.input_ids
        mask = [1 if (a < end and b > start) else 0 for a, b in enc.offset_mapping]
        if len(ids) > self.cfg.context_tokens:
            ids, mask = ids[-self.cfg.context_tokens:], mask[-self.cfg.context_tokens:]
        mask[0] = 0  # the first token has nothing before it to be predicted from
        n = sum(mask)
        if n == 0:
            return None
        input_ids = torch.tensor([ids], device=self.device)
        target_mask = torch.tensor(mask[1:], dtype=torch.bool, device=self.device)
        with self.lock:
            if learn:
                self._fade_fast(self.cfg.wake_decay)
            with torch.set_grad_enabled(learn):
                logits = self.model(input_ids=input_ids, use_cache=False).logits[0, :-1].float()
                loss = F.cross_entropy(logits[target_mask], input_ids[0, 1:][target_mask])
            bits = float(loss.detach()) / LN2
            if learn:
                self._wake_step(loss, bits)
            self.vitals["tokens_heard"] += n
            self.vitals["surprise_bits"] = bits
        return bits

    # ---------------------------------------------------------------- reflect

    def _teacher(self, said: str | list[str], question: str, background: bool = False) -> dict:
        """The frozen base answers ``question`` with ``said`` in view (one
        message, or an earlier and a later one). The result says whether the
        answer is a fact that what was said supports."""
        rec = self._generate(reflection.teacher_messages(said, question), self.cfg.answer_max_tokens,
                             base=True, background=background, record=True)
        text = said if isinstance(said, str) else " ".join(said)
        rec["supported"] = (rec["finished"] and grounded(question, rec["text"], text)
                            and not echoes_speaker(rec["text"], text))
        return rec

    def _revise(self, lesson: dict, background: bool = False) -> list[Item]:
        """Does this message change the answer to something learned earlier?
        Older questions whose source or answer shares a word with it are put
        to the teacher again, with the old message and the new one in view.
        An answer that now draws on the new message replaces the old one."""
        said = lesson["source"]
        if len(said.split()) > 300:
            return []
        said_words = set(content_words(said))
        with self.lock:
            older = [it for it in self.deck.active()
                     if it.kind == "fact" and it.lesson != lesson["id"] and it.source
                     and (set(content_words(it.source)) | set(content_words(it.a))) & said_words]
        revised: list[Item] = []
        for old in older[-self.cfg.revisions_per_lesson:]:
            rec = self._teacher([old.source, said], old.q, background)
            changed = set(content_words(rec["text"])) - set(content_words(old.a)) - set(content_words(old.q))
            if rec["supported"] and changed & said_words:
                item = self._add_item(old.q, rec, said, "fact", lesson["id"])  # retires the old answer
                if item:
                    revised.append(item)
                    self._notify("revised", old=old, item=item)
        return revised

    def _teacher_opening(self, said: str, questions: list[str], background: bool = False) -> list[int]:
        """The first token the frozen base would answer each question with,
        given ``said``. A few questions per pass, so the lock is never held long."""
        firsts: list[int] = []
        for i in range(0, len(questions), 6):
            rows = [self._ids(self._render(reflection.teacher_messages(said, q), True)) for q in questions[i : i + 6]]
            width = max(len(r) for r in rows)
            input_ids = torch.full((len(rows), width), self.pad_id, dtype=torch.long)
            attention = torch.zeros((len(rows), width), dtype=torch.long)
            for j, r in enumerate(rows):
                input_ids[j, : len(r)] = torch.tensor(r, dtype=torch.long)
                attention[j, : len(r)] = 1
            self._bg_gate(background)
            with torch.no_grad():
                logits = self._forward(True, input_ids=input_ids.to(self.device), attention_mask=attention.to(self.device), use_cache=False).logits
            firsts += [int(logits[j, len(r) - 1].argmax()) for j, r in enumerate(rows)]
        return firsts

    def _mark_answered(self, question: str) -> None:
        """A stock question that now has an answer is no longer held to "I don't know"."""
        for stock in anchor_prompts.UNKNOWN:
            if stock not in self._answered and (stock == question or jaccard(stock, question) >= 0.8):
                self._answered.add(stock)

    def _add_item(self, question: str, rec: dict, source: str, kind: str, lesson: int | None) -> Item | None:
        with self.lock:
            item = self.deck.add(question, rec["text"], source=source, kind=kind, lesson=lesson)
            if item:
                self._soft[item.id] = (rec["ids"], rec["top_idx"], rec["top_p"])
            if kind != "unknown":
                self._mark_answered(question)
            self._dirty = True
        return item

    def _reflect(self, lesson: dict, background: bool = False) -> list[Item]:
        """Turn a message into study items: write the questions it answers,
        then record how the base answers each with the message in view."""
        said = lesson["source"]
        added: list[Item] = []
        view = said if len(said.split()) <= 300 else None  # what the teacher sees
        for piece in chunks(said, self.cfg.reflect_chunk_words):
            raw = self._generate(reflection.question_messages(piece), self.cfg.reflect_max_tokens, sample=False,
                                 base=self.cfg.reflect_with_base, background=background)
            for q in parse_questions(raw, piece, self.cfg.questions_per_piece):
                rec = self._teacher(view or piece, q, background)
                if rec["supported"]:
                    item = self._add_item(q, rec, piece, "fact", lesson["id"])
                    if item:
                        added.append(item)
                elif rec["finished"] and abstains(rec["text"]):
                    lesson["probes"].append(q)  # a question this message does not answer
            # Does this message answer one of the stock personal questions the
            # mind is otherwise held to "I don't know" on? Whatever wording was
            # used, the teacher can tell: every open stock question is put to
            # it with the message in view. One batched pass finds the ones it
            # would not open with "I (don't know)", and only those are answered
            # in full.
            still_open = [p for p in anchor_prompts.UNKNOWN if p not in self._answered]
            for stock, first in zip(still_open, self._teacher_opening(view or piece, still_open, background)):
                if first == self._abstain_id:
                    continue
                rec = self._teacher(view or piece, stock, background)
                if rec["supported"]:
                    item = self._add_item(stock, rec, piece, "fact", lesson["id"])
                    if item:
                        added.append(item)
        if added:
            added += self._revise(lesson, background)
        with self.lock:
            lesson["stage"] = "study" if added else "done"
            self.vitals["lessons"] += 1
            self._dirty = True
        if added:
            self._notify("noted", items=added)
        return added

    def _check(self, lesson: dict, background: bool = False) -> list[Item]:
        """Self-examination after studying a message: ask about things it did
        NOT say. If words the mind just learned come out, the base (with the
        message in view) is asked what the answer should have been, and a
        "you never told me that" becomes something to study."""
        with self.lock:
            mine = [it for it in self.deck.items if it.lesson == lesson["id"] and it.kind == "fact"]
            lesson["stage"] = "done"
            self._dirty = True
        if not mine:
            return []
        fresh = set()
        for it in mine:
            fresh |= set(content_words(it.a)) - set(content_words(it.q))
        asked = {" ".join(content_words(it.q)) for it in mine}
        still_open = [p for p in anchor_prompts.UNKNOWN if p not in self._answered]
        nearby = sorted(still_open, key=lambda p: -max(jaccard(p, it.q) for it in mine))
        probes = lesson["probes"][: self.cfg.probes_per_lesson] + nearby[: self.cfg.probes_per_lesson]
        said = lesson["source"] if len(lesson["source"].split()) <= 300 else mine[0].source
        caught: list[Item] = []
        for q in dict.fromkeys(probes):
            if " ".join(content_words(q)) in asked:
                continue
            answer = self._generate(self._fresh_chat(q), self.cfg.answer_max_tokens, sample=False,
                                    background=background)
            if not (set(content_words(answer)) & fresh) - set(content_words(q)):
                continue  # nothing it just learned came out
            rec = self._teacher(said, q, background)
            if rec["supported"]:
                self._add_item(q, rec, said, "fact", lesson["id"])  # it generalised correctly: keep it
            elif rec["finished"] and abstains(rec["text"]):
                item = self._add_item(q, rec, said, "unknown", lesson["id"])
                if item:
                    caught.append(item)
                    self._notify("caught", question=q, said=answer, item=item)
        if caught:
            with self.lock:
                self.vitals["caught"] += len(caught)
        return caught

    def teach(self, question: str, answer: str) -> Item | None:
        """Put a question and its answer straight into the study deck."""
        with self.lock:
            item = self.deck.add(question.strip(), answer.strip(), source="taught directly", kind="taught")
            self._mark_answered(question)
            self._dirty = True
        self._kick.set()
        return item

    # ------------------------------------------------------------------ sleep

    def _kl(self, logits: torch.Tensor, top_idx: torch.Tensor, top_p: torch.Tensor) -> torch.Tensor:
        """KL(recorded || now) per position, on the recorded top tokens plus
        one bucket for everything else."""
        top_idx, top_p = top_idx.to(self.device, torch.long), top_p.to(self.device)
        logq = F.log_softmax(logits, -1).gather(-1, top_idx)
        p_rest = (1.0 - top_p.sum(-1)).clamp(min=1e-6)
        q_rest = (1.0 - logq.exp().sum(-1)).clamp(min=1e-6)
        return (top_p * (top_p.clamp(min=1e-9).log() - logq)).sum(-1) + p_rest * (p_rest.log() - q_rest.log())

    def _study(self, batch: list[Item]):
        """One forward pass over a batch of study items. Returns the loss to
        minimise and, per item, its cross-entropy (nats/token) and whether
        every token of the answer is already the model's first choice."""
        examples = [self._example(it) for it in batch]
        width = max(len(ids) for ids, _ in examples)
        input_ids = torch.full((len(batch), width), self.pad_id, dtype=torch.long)
        attention = torch.zeros((len(batch), width), dtype=torch.long)
        for i, (ids, _) in enumerate(examples):
            input_ids[i, : len(ids)] = torch.tensor(ids, dtype=torch.long)
            attention[i, : len(ids)] = 1
        input_ids, attention = input_ids.to(self.device), attention.to(self.device)
        logits = self.model(input_ids=input_ids, attention_mask=attention, use_cache=False).logits.float()
        losses, ces, right = [], [], []
        for i, (it, (ids, start)) in enumerate(zip(batch, examples)):
            lg = logits[i, start - 1 : len(ids) - 1]  # the positions that predict the answer
            target = input_ids[i, start : len(ids)]
            ce = F.cross_entropy(lg, target)
            soft = self._soft.get(it.id)
            if soft is not None and self.cfg.soft_weight > 0:
                loss = self.cfg.soft_weight * self._kl(lg, soft[1], soft[2]).mean() + self.cfg.hard_weight * ce
            else:
                loss = ce
            losses.append(loss)
            ces.append(float(ce.detach()))
            right.append(bool((lg.argmax(-1) == target).all()))
        return torch.stack(losses).mean(), ces, right

    def _pick_anchors(self) -> list[str]:
        """One prompt from each pool: general ability, and stock personal
        questions nothing it was told answers. Recording how the base answers
        a prompt costs a short generation, so each pool of recorded anchors
        is grown gradually rather than at birth."""
        pools = [anchor_prompts.GENERAL]
        if self.cfg.unknown_anchors:
            pools.append([p for p in anchor_prompts.UNKNOWN if p not in self._answered])
        picked = []
        for pool in pools:
            built = [p for p in pool if p in self._anchors]
            fresh = [p for p in pool if p not in self._anchors]
            if fresh and (len(built) < 4 or self.rng.random() < 0.25):
                picked.append(self.rng.choice(fresh))
            elif built:
                picked.append(self.rng.choice(built))
        return picked

    def _anchor_loss(self, prompts: list[str]) -> torch.Tensor:
        """KL(base || now) along the base's own replies to the anchor prompts."""
        rows = []
        for prompt in prompts:
            ids, top_idx, top_p = self._anchors[prompt]
            prefix = self._ids(self._render(self._fresh_chat(prompt), True))
            rows.append((prefix + ids.tolist(), len(prefix), top_idx, top_p))
        width = max(len(r[0]) for r in rows)
        input_ids = torch.full((len(rows), width), self.pad_id, dtype=torch.long)
        attention = torch.zeros((len(rows), width), dtype=torch.long)
        for i, (ids, _, _, _) in enumerate(rows):
            input_ids[i, : len(ids)] = torch.tensor(ids, dtype=torch.long)
            attention[i, : len(ids)] = 1
        logits = self.model(input_ids=input_ids.to(self.device), attention_mask=attention.to(self.device), use_cache=False).logits.float()
        kls = [self._kl(logits[i, start - 1 : len(ids) - 1], top_idx, top_p).mean()
               for i, (ids, start, top_idx, top_p) in enumerate(rows)]
        return torch.stack(kls).mean()

    def sleep_step(self, background: bool = False) -> dict | None:
        """One step of consolidation. Returns None when there is nothing to study."""
        if not self.deck.pending():
            return None
        anchors = self._pick_anchors() if self.cfg.anchor_weight > 0 else []
        for anchor in anchors:
            if anchor not in self._anchors:
                rec = self._generate(self._fresh_chat(anchor), self.cfg.anchor_max_tokens, base=True,
                                     background=background, record=True)
                with self.lock:
                    self._anchors[anchor] = (rec["ids"], rec["top_idx"], rec["top_p"])
        self._bg_gate(background)
        with self.lock:
            batch = self.deck.batch(self.cfg.batch_size, self.cfg.replay_per_batch, self.rng)
            if not any(it.pending for it in batch):
                return None
            loss, ces, right = self._study(batch)
            anchors = [a for a in anchors if a not in self._answered]
            kl = self._anchor_loss(anchors) if anchors else None
            self._step(loss + self.cfg.anchor_weight * kl if kl is not None else loss)
            learned = []
            for it, ce, ok in zip(batch, ces, right):
                it.visits += 1
                it.loss = ce
                it.streak = it.streak + 1 if ok else 0
                if it.state == "new":
                    # Stop on behaviour, not on a loss driven to zero: studying
                    # past the point of knowing the answer costs other things.
                    if it.streak >= self.cfg.learned_streak:
                        it.state, it.learned_loss = "learned", ce
                        learned.append(it)
                    elif it.visits >= self.cfg.max_visits:
                        it.state = "stuck"
                elif it.state == "learned" and self._slipped(it, ce, ok):
                    it.state, it.visits = "new", 0  # study it again
            self.vitals["sleep_steps"] += 1
        if learned:
            self._notify("learned", items=learned)
        return {"loss": float(loss.detach()), "kl": float(kl.detach()) if kl is not None else None,
                "pending": len(self.deck.pending()), "learned": learned}

    def _slipped(self, item: Item, ce: float, ok: bool) -> bool:
        """A learned item has slipped when it is no longer answered exactly
        AND its loss has clearly risen since it was learned. The second
        condition keeps an answer with two near-equal wordings from being
        reopened every time the lead between them changes hands."""
        return not ok and ce > (item.learned_loss or 0.0) + self.cfg.slip_margin

    def review(self) -> int:
        """Re-test every learned memory once and reopen the ones that slipped."""
        slipped = 0
        learned = self.deck.learned()
        for i in range(0, len(learned), 8):
            group = learned[i : i + 8]
            with self.lock, torch.no_grad():
                _, ces, right = self._study(group)
                for it, ce, ok in zip(group, ces, right):
                    it.loss = ce
                    if self._slipped(it, ce, ok):
                        it.state, it.visits, it.streak = "new", 0, 0
                        slipped += 1
        return slipped

    def _advance(self, background: bool = False) -> bool:
        """Move one lesson one stage forward, if any is ready."""
        with self.lock:
            lesson = next((l for l in self.lessons if l["stage"] == "reflect"), None)
        if lesson:
            self._reflect(lesson, background)
            return True
        with self.lock:
            pending = {it.lesson for it in self.deck.pending()}
            lesson = next((l for l in self.lessons if l["stage"] == "study" and l["id"] not in pending), None)
        if lesson:
            self._check(lesson, background)
            return True
        return False

    def digest(self, max_steps: int | None = None, progress: Callable[[dict], None] | None = None) -> int:
        """Do, right now, everything the dreaming thread would get round to:
        reflect on what was said, study it, check it. Returns the number of
        consolidation steps taken."""
        steps = 0
        while max_steps is None or steps < max_steps:
            info = self.sleep_step()
            if info is not None:
                steps += 1
                if progress:
                    progress(info)
            elif not self._advance():
                break
        return steps

    # ------------------------------------------------------------ living loop

    def _new_lesson(self, text: str) -> None:
        with self.lock:
            number = max([l["id"] for l in self.lessons] + [it.lesson or 0 for it in self.deck.items] + [0]) + 1
            self.lessons = [l for l in self.lessons if l["stage"] != "done"]
            self.lessons.append({"id": number, "source": text, "stage": "reflect", "probes": []})
            self._dirty = True
            # On disk at once: a message is not lost if the process dies
            # before it has been studied. It is picked up at the next start.
            atomic_write(self.life / "lessons.json", json.dumps([l for l in self.lessons if l["stage"] != "done"]))

    def _clean(self, text: str) -> str:
        """Chat control tokens typed by a person are text, not structure."""
        for token in self.tok.all_special_tokens:
            text = text.replace(token, "")
        return text.strip()

    def chat(self, text: str, on_token: Callable[[str], None] | None = None,
             max_new_tokens: int | None = None, sample: bool = True) -> dict:
        """One turn of life: hear, answer, remember, and queue the message
        for reflection."""
        text = self._clean(text)
        with self._attending():
            self._trim_context()
            bits = self.hear(text)
            self.context.append({"role": "user", "content": text})
            reply = self._generate(self._sys() + self.context, max_new_tokens or self.cfg.max_new_tokens,
                                   sample=sample, on_token=on_token)
            self.context.append({"role": "assistant", "content": reply})
            with self.lock:
                self.vitals["turns"] += 1
                self.vitals["tokens_spoken"] += len(self._ids(reply))
                self.journal.append({"t": time.time(), "session": self.vitals["sessions"], "user": text,
                                     "mind": reply, "surprise_bits": bits})
            self._new_lesson(text)
        return {"reply": reply, "surprise_bits": bits}

    def listen(self, text: str) -> float | None:
        """Hear something and queue it for reflection, without replying."""
        text = self._clean(text)
        with self._attending():
            bits = self.hear(text)
            self._new_lesson(text)
        return bits

    def ask(self, question: str, max_new_tokens: int = 48, base: bool = False) -> str:
        """Answer one question in an EMPTY context, greedily, with no learning
        and no trace left. This is how recall is tested."""
        with self._attending():
            return self._generate(self._fresh_chat(self._clean(question)), max_new_tokens, sample=False, base=base)

    def new_session(self) -> None:
        """Empty the context window. What sleep consolidated stays; what was
        only picked up while reading (the fast weights) is let go."""
        with self.lock:
            self._fade_fast(1.0)
            self.context = []

    def forget(self) -> None:
        """Erase the record of what happened: the journal, messages not yet
        studied, the context, and the note on each study item of the sentence
        it came from. The weights are untouched and the bare questions and
        answers are kept for rehearsal, so the mind still knows what it
        learned and no longer has any record of being told."""
        with self.lock:
            self.journal.wipe()
            self.lessons.clear()
            for it in self.deck.items:
                it.source = ""
            self.deck.items = [it for it in self.deck.items if it.state != "retired"]
            self._fade_fast(1.0)
            self.context = []
            self._dirty = True
            self.save()

    @property
    def busy(self) -> bool:
        return any(l["stage"] != "done" for l in self.lessons) or bool(self.deck.pending())

    # --------------------------------------------------------------- dreaming

    def start_dreaming(self) -> None:
        """Start the background thread that reflects, studies and checks
        whenever the mind is not being spoken with."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._dream, name="dreaming", daemon=True)
        self._thread.start()

    def stop_dreaming(self) -> None:
        self._stop.set()
        self._kick.set()
        if self._thread:
            self._thread.join()
            self._thread = None

    def _dream(self) -> None:
        while not self._stop.is_set():
            try:
                if self.sleep_step(background=True) is not None:
                    continue
                if self._advance(background=True):
                    continue
                if self._dirty:
                    self.save()
                    self._notify("rested")
                self._kick.wait(timeout=1.0)
                self._kick.clear()
            except Exception as exc:  # a bad dream must not end the life
                self._notify("error", error=repr(exc))
                time.sleep(1.0)
