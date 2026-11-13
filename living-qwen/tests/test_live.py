"""Live tests with a real model. They are skipped unless you point them at one:

    LIVING_QWEN_MODEL=Qwen/Qwen3-1.7B python -m pytest tests/test_live.py -s

They take a few minutes on a CPU.
"""
import os
import time

import pytest

MODEL = os.environ.get("LIVING_QWEN_MODEL")
pytestmark = pytest.mark.skipif(not MODEL, reason="set LIVING_QWEN_MODEL to run the live tests")


def test_learns_in_the_background_while_being_spoken_with(tmp_path):
    from living import LivingMind

    events = []
    mind = LivingMind(MODEL, tmp_path / "life", seed=0, on_event=lambda kind, data: events.append(kind))
    question = "What is my dog's name?"
    assert "zorblat" not in mind.ask(question).lower()

    mind.cfg.dream_while_speaking = True
    mind.start_dreaming()
    mind.chat("My dog's name is Zorblat.", max_new_tokens=24, sample=False)
    steps_before = mind.vitals["sleep_steps"]
    deadline = time.time() + 1500
    spoken = 0
    while mind.busy and time.time() < deadline:
        # speaking and studying share the weights: a few tokens, a step, a few tokens...
        spoken += len(mind.ask("Count from one to twenty in words.", 24))
    mind.stop_dreaming()
    mind.save()
    assert not mind.busy, "did not finish studying in time"
    assert "error" not in events, events
    assert mind.vitals["sleep_steps"] > steps_before and spoken > 0

    again = LivingMind(None, tmp_path / "life", seed=0)  # a new process would start here
    assert again.context == []
    assert "zorblat" in again.ask(question).lower()
    assert "zorblat" not in again.ask(question, base=True).lower()
    again.forget()  # journal and notes gone, weights untouched
    assert "zorblat" in again.ask(question).lower()
