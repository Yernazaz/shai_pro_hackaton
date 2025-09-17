import inspect

def _getargspec_wrapper(func):
    full = inspect.getfullargspec(func)
    return (full.args, full.varargs, full.varkw, full.defaults)

inspect.getargspec = _getargspec_wrapper

import re
from typing import Optional
import pymorphy2

morph = pymorphy2.MorphAnalyzer()


_pattern = re.compile(
    r"""
    \bтоп\b          
    \s*              
    (?P<num1>\d+)    
    |
    (?P<num2>\d+)    
    (?:\s+\w+){0,3}  
    \s+              
    (?:сам[а-яё]+    
     |лучш[а-яё]+)   
    """,
    flags=re.IGNORECASE | re.VERBOSE | re.UNICODE
)

def extract_limit_via_regex(text: str) -> Optional[int]:
    match = _pattern.search(text)
    if not match:
        return None
    if match.group("num1"):
        return int(match.group("num1"))
    if match.group("num2"):
        return int(match.group("num2"))
    return None

def extract_limit_via_pymorphy(text: str) -> Optional[int]:
    tokens = re.findall(r"\d+|\w+", text.lower())

    for i, tok in enumerate(tokens):
        if not tok.isdigit():
            continue

        num_int = int(tok)

        if i + 2 < len(tokens):
            t1 = tokens[i + 1]
            t2 = tokens[i + 2]

            p1 = morph.parse(t1)[0]
            p2 = morph.parse(t2)[0]

            if (p1.tag.POS in {"ADJF", "ADJS"}) and (p2.tag.POS == "NOUN"):
                return num_int

        for offset in range(1, 4):  
            adj_idx = i + offset
            noun_idx = i + offset + 1
            if noun_idx >= len(tokens):
                break

            p_adj = morph.parse(tokens[adj_idx])[0]
            p_noun = morph.parse(tokens[noun_idx])[0]
            if (p_adj.tag.POS in {"ADJF", "ADJS"}) and (p_noun.tag.POS == "NOUN"):
                return num_int

    return None

def extract_limit(text: str) -> Optional[int]:
    by_regex = extract_limit_via_regex(text)
    if by_regex is not None:
        return by_regex

    by_morph = extract_limit_via_pymorphy(text)
    if by_morph is not None:
        return by_morph

    return None


# ------------------------ Примеры тестов ------------------------

if __name__ == "__main__":
    tests = [
        # 1. regex-кейсы
        "выведи 5 самых дорогих посещении за 2 месяца",
        "покажи 10 лучших фильмов 2024 года",
        "давай 12 лучших сериалов этого года",
        "топ 5 фильмов этого года",
        "Топ10 сериалов",
        "ТОП   20 лучших ресторанов города",

        # 2. «порядок ADJ+NOUN» (pymorphy2)
        "выведи 5 дорогих посещении",
        "покажи 10 популярных книг",
        "найди 7 новых моделей телефон",
        "покажи 5 очень дорогих зданий",

        # 3. смешанные
        "хочу 3 самых новых книги по программированию",
        "отсортируй 7 самых популярных ресторанов",

        # 4. негативные
        "найди пять самых больших озёр",     # «пять» прописью → None
        "нет предела этим словам",           # нет числа → None
        "покажи 5 самых большая квартира",   # «большая» ADJF, без «сам/лучш»,
                                              # но pymorphy2 увидит ADJ+NOUN → 5
        "хочу топовые 5 предложений",        # «топовые 5» не наш шаблон → None
        "пять топ 5 вещей",                  # regex найдёт «топ 5» → 5
    ]

    for s in tests:
        print(f"«{s}» → {extract_limit(s)}")
