import re
from typing import Optional
import pymorphy2
import inspect

def _getargspec_wrapper(func):
    full = inspect.getfullargspec(func)
    return (full.args, full.varargs, full.varkw, full.defaults)

inspect.getargspec = _getargspec_wrapper

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
