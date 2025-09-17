import numpy as np
from typing import Tuple
from app.agents.intent_corpus import intent_definitions
from app.utils.embeddings import get_sentence_model, DEFAULT_MODEL

model = get_sentence_model(DEFAULT_MODEL)

def compute_intent_embeddings(definitions):
    texts, labels = [], []
    for intent in definitions:
        for ex in intent["examples"]:
            texts.append(ex)
            labels.append(intent["name"])
    embeddings = model.encode(texts, convert_to_numpy=True)
    return embeddings, labels

def build_fallback_prompt(user_query: str, definitions):
    lines = ["Ниже представлены категории намерений и примеры запросов пользователей.\n"]
    for intent in definitions:
        lines.append(f"Категория: {intent['name']}\nОписание: {intent['description']}")
        for example in intent["examples"]:
            lines.append(f" - {example}")
        lines.append("")
    lines.append(f"\nЗапрос пользователя:\n\"{user_query}\"\nКакой это тип намерения?")
    lines.append("Ответь только названием категории.")
    return "\n".join(lines)
