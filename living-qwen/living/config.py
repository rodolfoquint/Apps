"""Every knob of a living mind, in one place."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class Config:
    # --- plastic weights: LoRA adapters on a frozen base --------------------
    lora_r: int = 16
    lora_alpha: int = 32
    lora_targets: tuple = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")

    # --- wake: every incoming message is predicted and scored as it is read ---
    wake_learning: bool = False  # also take a fading step on the weights from that same pass
    wake_lr: float = 0.05  # step length at full surprise (the gradient is clipped to grad_clip)
    wake_floor_bits: float = 1.5  # below this surprise nothing is learned from a message
    wake_span_bits: float = 4.0  # surprise above the floor at which the step reaches full length
    wake_decay: float = 0.3  # share of the fast weights that fades each turn

    # --- reflection: turning what was heard into things to study -------------
    reflect_with_base: bool = True  # study questions are written by the frozen base
    reflect_max_tokens: int = 160
    reflect_chunk_words: int = 60
    questions_per_piece: int = 8
    answer_max_tokens: int = 48
    probes_per_lesson: int = 3  # per source: questions it was NOT told, asked after studying
    revisions_per_lesson: int = 6  # older answers re-examined when a new message touches them

    # --- sleep: consolidation of study items into the weights ----------------
    sleep_lr: float = 2e-4
    warmup_steps: int = 8  # the first steps of a life are taken gently
    batch_size: int = 6
    replay_per_batch: int = 2  # slots reserved for already-learned memories
    learned_streak: int = 2  # exact answers in a row before an item counts as learned
    slip_margin: float = 0.3  # rise in loss (nats/token) before a learned item is studied again
    max_visits: int = 40  # give up on an item after this many visits
    grad_clip: float = 1.0
    weight_decay: float = 0.0
    soft_weight: float = 1.0  # match the teacher's whole next-token distribution (distillation)
    hard_weight: float = 0.3  # plus some plain cross-entropy on the teacher's words, to settle near-ties
    soft_topk: int = 32  # how much of each distribution is recorded
    anchor_weight: float = 1.0  # strength of the pull toward the base model on unrelated prompts
    unknown_anchors: bool = True  # also hold stock personal questions it was never told the answer to
    anchor_max_tokens: int = 24

    # --- speaking ------------------------------------------------------------
    max_new_tokens: int = 256
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    context_tokens: int = 1500
    system_prompt: str | None = None  # None: whatever the model's template does by default

    # --- concurrency ---------------------------------------------------------
    # Keep consolidating between spoken tokens: one step every few tokens of a
    # reply. None means yes on a GPU or Apple Silicon and no on a CPU, where a
    # step takes seconds and would make replies crawl.
    dream_while_speaking: bool | None = None
    dream_every_tokens: int = 12

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lora_targets"] = list(self.lora_targets)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in known}
        if "lora_targets" in d:
            d["lora_targets"] = tuple(d["lora_targets"])
        return cls(**d)
