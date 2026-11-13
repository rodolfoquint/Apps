"""The machinery of a living mind, exercised on a tiny random model.

Nothing sensible can be learned by a two-layer random network, so these tests
check mechanics only: that studying lowers the loss on what is studied, that
a life survives being saved and reloaded bit for bit, that forgetting leaves
the weights alone, that wake learning fades away completely, and that the
dreaming thread runs alongside speaking without errors.

They need a Qwen tokenizer: from LIVING_QWEN_TOKENIZER or LIVING_QWEN_MODEL if set, else downloaded
from Hugging Face (a few MB). Without either they are skipped.
"""
import os
import time

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    source = os.environ.get("LIVING_QWEN_TOKENIZER") or os.environ.get("LIVING_QWEN_MODEL") or "Qwen/Qwen3-0.6B"
    try:
        tok = transformers.AutoTokenizer.from_pretrained(source)
    except Exception as exc:  # no network and no local model
        pytest.skip(f"no Qwen tokenizer available: {exc}")
    cfg = transformers.Qwen2Config(
        vocab_size=len(tok), hidden_size=32, intermediate_size=64, num_hidden_layers=2,
        num_attention_heads=2, num_key_value_heads=1, max_position_embeddings=1024,
    )
    torch.manual_seed(0)
    path = tmp_path_factory.mktemp("tiny-qwen")
    transformers.Qwen2ForCausalLM(cfg).save_pretrained(path)
    tok.save_pretrained(path)
    return str(path)


def make(tiny, life, **overrides):
    from living import Config, LivingMind

    cfg = Config(sleep_lr=1e-2, warmup_steps=1, max_visits=400, anchor_max_tokens=4, answer_max_tokens=6,
                 reflect_max_tokens=8, max_new_tokens=6)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return LivingMind(tiny, life, cfg, device="cpu", seed=0)


def plastic(mind):
    return torch.cat([p.detach().flatten().clone() for p in mind.params])


def test_studying_lowers_loss_and_survives_reload(tiny, tmp_path):
    mind = make(tiny, tmp_path / "life")
    assert mind.newborn and float(plastic(mind).abs().sum()) > 0  # LoRA A is random, B is zero
    item = mind.teach("What is my dog's name?", "Your dog's name is Zorblat.")
    losses = []
    for _ in range(30):
        assert mind.sleep_step() is not None
        losses.append(item.loss)
    assert losses[-1] < losses[0] - 0.2, losses  # a random two-layer net cannot do much better
    assert item.visits == 30 and mind.vitals["sleep_steps"] == 30
    assert mind._anchors  # it was also holding itself to the base on anchor prompts
    item.state = "learned"
    answer = mind.ask("What is my dog's name?", 12)
    before = plastic(mind)
    mind.save()

    again = make(tiny, tmp_path / "life")
    assert not again.newborn and again.context == []
    assert torch.equal(plastic(again), before)
    assert again.ask("What is my dog's name?", 12) == answer
    assert [(it.state, it.visits) for it in again.deck.items] == [("learned", 30)]
    assert again.vitals["sessions"] == 2

    again.journal.append({"user": "My dog's name is Zorblat."})
    again.forget()  # the record goes; weights and rehearsal material stay
    assert again.journal.read() == [] and again.lessons == []
    assert [(it.q, it.source) for it in again.deck.items] == [("What is my dog's name?", "")]
    assert torch.equal(plastic(again), before)
    assert again.ask("What is my dog's name?", 12) == answer


def test_a_message_survives_a_crash_before_it_is_studied(tiny, tmp_path):
    mind = make(tiny, tmp_path / "life")
    mind.listen("My dog's name is Zorblat.")  # queued for reflection; the process then dies without save()
    again = make(tiny, tmp_path / "life")
    assert [(l["source"], l["stage"]) for l in again.lessons] == [("My dog's name is Zorblat.", "reflect")]
    assert again.busy


def test_a_life_refuses_a_different_base_model(tiny, tmp_path):
    mind = make(tiny, tmp_path / "life")
    mind.save()
    from living import LivingMind

    with pytest.raises(ValueError):
        LivingMind("some/other-model", tmp_path / "life")


def test_wake_learning_fades_and_is_never_saved(tiny, tmp_path):
    mind = make(tiny, tmp_path / "life", wake_learning=True, wake_lr=0.5, wake_floor_bits=0.0)
    start = plastic(mind)
    bits = mind.hear("My dog's name is Zorblat.")
    assert bits is not None and bits > 0
    assert not torch.equal(plastic(mind), start)  # reading changed the weights
    assert mind.hear("My dog's name is Zorblat.", learn=False) < bits  # and it is less surprised now
    mind.save()  # only consolidated weights are written...
    moved = plastic(mind)
    assert not torch.equal(moved, start)  # ...while the live ones keep their fast component
    assert torch.equal(plastic(make(tiny, tmp_path / "life")), start)
    mind.new_session()  # the end of a conversation lets it go
    assert torch.allclose(plastic(mind), start, atol=1e-6)


def test_teacher_opening_and_recording_shapes(tiny, tmp_path):
    mind = make(tiny, tmp_path / "life")
    questions = [f"What is my thing number {i}?" for i in range(8)]
    firsts = mind._teacher_opening("I have eight things.", questions)
    assert len(firsts) == 8 and all(isinstance(t, int) for t in firsts)
    rec = mind._generate(mind._fresh_chat("Hello!"), 5, base=True, record=True)
    assert len(rec["ids"]) == len(rec["top_idx"]) == len(rec["top_p"])
    assert rec["finished"] == (len(rec["ids"]) > 0 and int(rec["ids"][-1]) == mind.eot_id)
    assert rec["top_idx"].shape[1] == mind.cfg.soft_topk


def test_dreaming_alongside_speaking(tiny, tmp_path):
    events = []
    mind = make(tiny, tmp_path / "life", dream_while_speaking=True, dream_every_tokens=2, max_visits=5)
    mind.on_event = lambda kind, data: events.append(kind)
    mind.start_dreaming()
    items = [mind.teach(f"What is fact number {i}?", f"Fact number {i} is {i * 7}.") for i in range(3)]
    mind.chat("hello there", max_new_tokens=6)  # also queues a lesson for reflection
    deadline = time.time() + 120
    while mind.busy and time.time() < deadline:
        mind.ask("Are you studying?", 6)  # speaking and studying share the weights
    mind.stop_dreaming()
    assert not mind.busy, [it.state for it in items]
    assert "error" not in events, events
    assert all(it.state in ("learned", "stuck") for it in items)
    assert mind.vitals["turns"] == 1 and len(mind.journal.read()) == 1
    mind.save()
    assert make(tiny, tmp_path / "life").vitals["sleep_steps"] == mind.vitals["sleep_steps"]
