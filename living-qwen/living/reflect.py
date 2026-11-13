"""Reflection: how something said once becomes something known.

Two prompts, both answered by the frozen base model ("the mind as it was
born"), so that study material never drifts with what has been learned.

1. Questions. Given a message, write the questions its speaker might later
   ask to check it was remembered: several wordings, both directions.
2. Teacher. With the message in view, answer one question in a sentence, or
   say it was never told. The answer, and how sure the teacher was of each
   word, is what the mind then learns to give with an EMPTY context. This is
   context distillation: knowledge moves from the context into the weights.

The teacher is also the judge of mistakes and of change. After studying, the
mind is asked things it was not told; if a freshly learned fact comes out
anyway, the teacher's "I don't know" for that question becomes a study item
too. And when a new message touches something learned earlier ("actually, I
moved to Lisbon"), the old question is put to the teacher again with both
messages in view; if the answer has changed, the new one replaces the old.
"""
from __future__ import annotations

QUESTION_SYSTEM = (
    "You write the questions a person might ask later to check whether you remember what they just told you. "
    "Write the questions from the person's side, using 'my' and 'I'. Give several questions for each fact, worded "
    "differently, and include questions that ask in the other direction, from the answer back to the thing. "
    "One question per line and nothing else. If the message tells you no facts about the person or the world "
    "(for example a greeting, a request, or a question), reply with exactly: NONE"
)

QUESTION_SHOTS = [
    (
        "I just adopted a parrot called Mango, he's three years old.",
        "What is my parrot's name?\nWhat did I name my parrot?\nWho is Mango?\nHow old is my parrot?\n"
        "What pet did I adopt?\nWhat kind of animal is Mango?",
    ),
    ("Can you help me write an email to my landlord?", "NONE"),
    (
        "I'm a nurse and I work night shifts at St. Mary's hospital.",
        "What is my job?\nWhat do I do for a living?\nWhere do I work?\nWhich hospital do I work at?\n"
        "What shifts do I work?\nWho works night shifts at St. Mary's hospital?",
    ),
    ("hi how are you?", "NONE"),
    (
        "The meeting with Dr. Patel got moved to Thursday at 3pm.",
        "When is the meeting with Dr. Patel?\nWhat day is my meeting with Dr. Patel?\n"
        "What time is the meeting on Thursday?\nWho is the Thursday 3pm meeting with?\n"
        "What is happening on Thursday at 3pm?",
    ),
]

TEACHER_SYSTEM = (
    "Answer the question in one short, complete sentence, using only what the person has told you in this "
    "conversation. Address the person as 'you'. Do not guess and do not infer: if they did not say it, say "
    "that you don't know."
)


def question_messages(said: str) -> list[dict]:
    msgs = [{"role": "system", "content": QUESTION_SYSTEM}]
    for example, questions in QUESTION_SHOTS:
        msgs.append({"role": "user", "content": example})
        msgs.append({"role": "assistant", "content": questions})
    msgs.append({"role": "user", "content": said})
    return msgs


def teacher_messages(said: str | list[str], question: str) -> list[dict]:
    """What the person said (one message, or an earlier one followed by a
    later one that may change it), then the question."""
    msgs = [{"role": "system", "content": TEACHER_SYSTEM}]
    for message in [said] if isinstance(said, str) else said:
        msgs.append({"role": "user", "content": message})
        msgs.append({"role": "assistant", "content": "Got it."})
    msgs.append({"role": "user", "content": question})
    return msgs
