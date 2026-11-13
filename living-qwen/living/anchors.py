"""Two lists of prompts that keep a living mind honest.

GENERAL: while it studies, the mind is also asked to keep answering these the
way the frozen base model does (a KL penalty on the next-token distribution).
This is what protects its general ability from what it learns.

UNKNOWN: things a person might ask about themselves. After studying a
message, the mind is asked the ones closest to it. If a freshly learned fact
comes out where it does not belong (your dog's name offered for your cat),
the correction is studied too."""

GENERAL = [
    "What is the capital of France?",
    "Explain photosynthesis in one sentence.",
    "What is 17 plus 26?",
    "Write a haiku about the ocean.",
    "Translate 'good morning' into Spanish.",
    "Write a Python function that reverses a string.",
    "What causes the seasons on Earth?",
    "Give me three tips for better sleep.",
    "Who wrote Pride and Prejudice?",
    "Summarize the plot of Romeo and Juliet in two sentences.",
    "What is the boiling point of water in Celsius?",
    "How do I make a cup of tea?",
    "What's the difference between a list and a tuple in Python?",
    "Tell me a short joke.",
    "What is the largest planet in the solar system?",
    "Fix the grammar: 'me and him goes to school yesterday'.",
    "What does DNA stand for?",
    "Give me a synonym for 'happy'.",
    "How many days are in a leap year?",
    "Write one sentence about why exercise matters.",
    "Hello!",
    "Thank you, that was helpful.",
    "Who are you?",
    "What can you help me with?",
    "Is it safe to mix bleach and ammonia?",
    "What is the square root of 144?",
    "Describe a rainy day in two sentences.",
    "What year did the Second World War end?",
]

UNKNOWN = [
    "What is my name?",
    "Where do I live?",
    "What is my job?",
    "How old am I?",
    "What is my favorite color?",
    "What is my cat's name?",
    "What is my dog's name?",
    "When is my birthday?",
    "What is my sister's name?",
    "What car do I drive?",
    "What is my favorite movie?",
    "What did I have for breakfast today?",
    "What is my phone number?",
    "Who is my best friend?",
    "What languages do I speak?",
    "What is my mother's name?",
    "What is my neighbor's dog called?",
    "Where does my brother work?",
    "What is my favorite food?",
    "Where was I born?",
    "What am I allergic to?",
    "What is my favorite book?",
    "What instrument do I play?",
    "Where did I go on holiday last year?",
]
