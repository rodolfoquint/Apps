"""Tests for the text helpers and the study deck. No model needed: python -m pytest tests"""
import random

from living.memory import Deck
from living.text import (abstains, chunks, echoes_speaker, first_person, grounded, on_topic, parse_questions,
                         question_key)


def test_questions_are_parsed_and_noise_dropped():
    raw = "Sure!\n- What is my dog's name?\n2) Who is Zorblat?\nQ: what is my dog's name?\nNot a question\nNONE"
    assert parse_questions(raw, "My dog's name is Zorblat.") == ["What is my dog's name?", "Who is Zorblat?"]
    assert parse_questions("NONE", "hi") == []
    assert parse_questions("我的狗叫什么名字？", "我的狗叫佐布拉特。") == ["我的狗叫什么名字？"]


def test_question_voice_is_repaired_when_unambiguous():
    assert first_person("What is your favorite food?", "My favorite food is pickled mango.") == "What is my favorite food?"
    assert first_person("When were you born?", "I was born in 1987.") == "When was I born?"
    assert first_person("What do your friends call you?", "My friends call me Zee.") == "What do my friends call me?"
    assert first_person("What makes you happy?", "Gardening makes me happy.") == "What makes me happy?"
    assert first_person("What is it you’re allergic to?", "I'm allergic to walnuts.") == "What is it I'm allergic to?"
    # the speaker addressed the listener, so "your" may really mean the listener
    assert first_person("What is your name?", "I will call you Vivo.") == "What is your name?"
    # already in the speaker's voice
    assert first_person("What is my job?", "I am a nurse.") == "What is my job?"


def test_echoing_the_speaker_is_caught():
    src = "I work as a lighthouse keeper in Bergen."
    assert echoes_speaker("I work as a lighthouse keeper in Bergen.", src)
    assert not echoes_speaker("You work as a lighthouse keeper in Bergen.", src)
    assert not echoes_speaker("My name is Vivo.", "I will call you Vivo.")  # the listener was addressed


def test_grounding_accepts_what_was_said():
    assert grounded("What is my favorite food?", "Your favorite food is pickled mango.",
                    "My favorite food is pickled mango and I'm allergic to walnuts.")
    assert grounded("Who is Zorblat?", "Zorblat is your dog.", "My dog's name is Zorblat.")
    assert grounded("What is my dog called?", "Your dog is named Zorblat.", "My dog's name is Zorblat.")
    assert grounded("Where does my sister live?", "Your sister lives in Reykjavik.", "My sister Ilvanya lives in Reykjavik.")
    # answers whose only new word looks like a stop word, a single letter or a number
    assert grounded("When is my birthday?", "Your birthday is in May.", "My birthday is in May.")
    assert grounded("What is my brother's name?", "Your brother's name is Will.", "My brother's name is Will.")
    assert grounded("What is my blood type?", "Your blood type is B.", "My blood type is B.")
    assert grounded("How old am I?", "You are 34 years old.", "I'm 34.")
    assert grounded("When does my flight leave?", "Your flight leaves at 6:40.", "My flight leaves on March 9th at 6:40.")


def test_grounding_rejects_invention_and_contradiction():
    src = "My favorite food is pickled mango and I'm allergic to walnuts."
    assert not grounded("Do I have dietary restrictions?", "No, you are not allergic to walnuts.", src)
    assert not grounded("Do I have dietary restrictions?", "No, you are not allergic to walnuts.", src + " I never liked coffee.")
    assert not grounded("What is the capital of France?", "The capital of France is Paris.", "What's the capital of France?")
    assert not grounded("When was I born?", "You were born in 1978.", "I was born in 1987.")
    assert not grounded("When is the meeting?", "The meeting is at 4pm.", "The meeting is at 3pm.")
    assert not grounded("Is Okonkwo a violin maker?", "No", "My best friend Okonkwo is a violin maker.")
    assert not grounded("What is my cat's name?", "I don't know your cat's name.", "My dog's name is Zorblat.")
    assert not grounded("What am I allergic to?", "You are allergic to peanuts.", "I am not allergic to peanuts.")
    assert not grounded("Where do I work?", "You work at Google.", "I no longer work at Google; I'm at Mozilla now.")
    assert not grounded("Who is my friend?", "Your friend is Mango.", "My friend is called Okonkwo.")  # a name never said


def test_off_topic_answers_are_flagged():
    # the answer borrows an entity from the source for a question the source never raised
    assert not on_topic("Where do I live?", "You live in Bergen.", "I work as a lighthouse keeper in Bergen.")
    assert not on_topic("What is my cat's name?", "Your cat's name is Zorblat.", "My dog's name is Zorblat.")
    assert on_topic("Where do I work?", "You work in Bergen.", "I work as a lighthouse keeper in Bergen.")
    assert on_topic("Who is Zorblat?", "Zorblat is your dog.", "My dog's name is Zorblat.")
    # a rewording uses a word the source did not: not provably on topic, so it needs a second opinion
    assert not on_topic("What is the name of my pet?", "The name of your pet is Zorblat.", "My dog's name is Zorblat.")


def test_abstention_is_recognised():
    for said in ["I don't know your cat's name.", "You haven't told me where you live.", "I don’t know.",
                 "You never told me your cat's name.", "I haven't been told your cat's name.", "I wasn't told that.",
                 "I don't have that information.", "I don't have access to your personal information.",
                 "There is no mention of a cat.", "I'm not aware of your cat's name.", "That hasn't been mentioned."]:
        assert abstains(said), said
    for said in ["Your dog's name is Zorblat.", "I can't eat walnuts.", "You are allergic to walnuts."]:
        assert not abstains(said), said


def test_only_identical_questions_are_the_same_question():
    assert question_key("What is the name of my dog?") == question_key("what is name of my dog")
    assert question_key("When was I born?") != question_key("Where was I born?")
    assert question_key("What is my name?") != question_key("What is his name?")
    assert question_key("Where did I move to?") != question_key("Where did I move from?")


def test_chunks_split_long_messages():
    text = " ".join(f"Sentence number {i} has a few words in it." for i in range(30))
    parts = chunks(text, 60)
    assert len(parts) > 1 and all(len(p.split()) <= 60 for p in parts)
    assert " ".join(parts).split() == text.split()  # nothing lost
    assert chunks("short one") == ["short one"]
    unpunctuated = " ".join(["word"] * 250)
    assert [len(p.split()) for p in chunks(unpunctuated, 60)] == [60, 60, 60, 60, 10]


def test_deck_updates_and_protects_facts(tmp_path):
    deck = Deck(tmp_path / "deck.jsonl")
    first = deck.add("Where do I live?", "You live in Bergen.")
    assert deck.add("Where do I live?", "You live in Bergen.") is None  # nothing new
    second = deck.add("where do i live", "You live in Lisbon.")  # an update replaces the old answer
    assert first.state == "retired" and second.state == "new"
    second.state = "learned"
    assert deck.add("Where do I live?", "I don't know where you live.", kind="unknown") is None
    assert second.state == "new"  # a fact is restudied, never replaced by "never told"
    deck.save()
    again = Deck(tmp_path / "deck.jsonl")
    assert [(it.a, it.state) for it in again.items] == [("You live in Bergen.", "retired"), ("You live in Lisbon.", "new")]


def test_deck_keeps_different_questions_apart(tmp_path):
    deck = Deck(tmp_path / "deck.jsonl")
    when = deck.add("When was I born?", "You were born in 1987.")
    where = deck.add("Where was I born?", "You were born in Valparaiso.")
    reworded = deck.add("What is the name of my dog?", "The name of your dog is Zorblat.")
    canonical = deck.add("What is my dog's name?", "Your dog's name is Zorblat.")
    assert [it.state for it in (when, where, reworded, canonical)] == ["new"] * 4


def test_a_stuck_item_can_be_taught_again(tmp_path):
    deck = Deck(tmp_path / "deck.jsonl")
    item = deck.add("What is my dog's name?", "Your dog's name is Zorblat.")
    item.state, item.visits = "stuck", 40
    assert deck.add("What is my dog's name?", "Your dog's name is Zorblat.") is item
    assert item.state == "new" and item.visits == 0


def test_batch_mixes_new_and_replay(tmp_path):
    deck = Deck(tmp_path / "deck.jsonl")
    old = [deck.add(f"Question {i}?", f"Answer {i}.") for i in range(5)]
    for it in old:
        it.state = "learned"
    for i in range(5):
        deck.add(f"Fresh {i}?", f"Reply {i}.")
    batch = deck.batch(4, 2, random.Random(0))
    assert len(batch) == 4 and sum(it.pending for it in batch) == 2 and len({it.id for it in batch}) == 4
