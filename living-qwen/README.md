# living-qwen

A small Qwen that keeps learning while you talk to it.

A language model normally has two separate modes. In training its weights
change. In use they are frozen, and whatever you tell it lives only in the
context window and is gone when the conversation ends. This project removes
that separation for a small open-weight Qwen: one process holds one set of
weights and reads, speaks and learns with them, interleaved. Tell it
something today, close the program, start it tomorrow with an empty context,
and it still knows. Nothing is looked up and no notes are put in the prompt.
The weights changed.

## Try it

```
pip install -r requirements.txt
python chat.py
```

The first run downloads `Qwen/Qwen3-1.7B` (about 4 GB) from Hugging Face. To
use a copy you already have, point at its folder:

```
python chat.py --model /path/to/Qwen3-1.7B
```

The folder must be in Hugging Face format (`config.json`, `model.safetensors`).
A GGUF file from Ollama or LM Studio cannot be trained, so for those use the
Hugging Face id of the same model instead. Any Qwen2.5 or Qwen3 chat model
should work. The 1.7B model is the smallest that writes its own study
material reliably (see "What was measured").

It runs on a CPU, and uses a GPU or Apple Silicon when there is one. On a
4-core CPU the 1.7B model speaks at about 5 tokens a second and takes one to
three minutes of background study to absorb a message.

A session looks like this:

```
> My dog's name is Zorblat.
That's a lovely name! How old is Zorblat?
  surprise 6.5 bits/token
  to study: What is my dog's name? -> Your dog's name is Zorblat.
  to study: Who is Zorblat? -> Zorblat is your dog.
  learned (6 visits): What is my dog's name?
  learned (7 visits): Who is Zorblat?
  rested and saved
> /quit

$ python chat.py            # later, a new process, an empty context
> What is my dog's name?
Your dog's name is Zorblat.
```

Commands inside the chat: `/new` (empty the context), `/sleep`, `/memories`,
`/vitals`, `/teach Q => A`, `/forget`, `/base QUESTION` (ask the untouched
model for comparison), `/quit`.

## How it lives

The base model is frozen. Everything experience changes is in a small set of
extra weights (LoRA adapters, about 1% of the model) that start at zero. The
whole life is a folder: those weights, a journal of what was said, and the
notes it is still studying.

Four things happen with the same weights, one token or one training step at
a time:

| | What happens | Why |
|---|---|---|
| **Wake** | Each incoming message is predicted token by token as it is read. The prediction error is shown as *surprise*. | It is the model's own measure of how new something is. |
| **Reflect** | It writes the questions that message could later be tested with, then answers each one with the message in view. The frozen base does this, so study material never drifts with what has been learned. | Training on the sentence itself barely helps a model answer questions about it. Training on questions does. |
| **Sleep** | It trains itself to give those same answers with an empty context, matching the full word-by-word probabilities of the answer it gave with the message in view. Each step also replays older memories and holds it close to the base model on unrelated prompts. | This is what moves a fact from the context into the weights without overwriting what was there. |
| **Check** | It asks itself about things it was *not* told. If a fresh fact comes out anyway (your dog's name offered for your cat), the correction becomes something to study. | A model that has just learned a fact will otherwise say it everywhere. |

Reflection, sleep and checking run in a background thread whenever you are
not being answered. With a GPU they also run between the words of a reply.

### What "at the same time" means here

There is no training phase and no inference phase, and no second copy of the
model. One lock guards the weights and is held for one token or one gradient
step at a time, so reading, speaking and learning take turns at that grain.
A reply can begin under one set of weights and finish under a slightly
different one.

There is also an optional, more literal form (`--wake-learning`): the pass
that reads your message also takes a small step on the weights, larger the
more surprising the message was. Those changes are kept apart from lasting
memory, fade a little every turn, are dropped when a conversation ends and
are never saved. It is off by default (see below).

### Forgetting where it came from

`/forget` erases the journal, the study notes and the context. The weights
are not touched, so what it learned is still there: it knows your dog's name
and has no record of ever being told.

## What was measured

RESULTS_PLACEHOLDER

## Limits

LIMITS_PLACEHOLDER

## Files

| | |
|---|---|
| `chat.py` | talk to it |
| `evaluate.py` | the measurements above |
| `living/mind.py` | the mind: wake, reflect, sleep, check, dreaming thread, saving |
| `living/reflect.py` | the two prompts used for reflection |
| `living/memory.py` | journal and study deck |
| `living/anchors.py` | prompts that hold it to the base model |
| `living/text.py` | parsing and the checks that keep invented answers out |
| `living/config.py` | every setting |
| `tests/` | unit tests, and an opt-in live test with a real model |
