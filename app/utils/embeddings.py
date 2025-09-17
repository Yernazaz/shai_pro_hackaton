from functools import lru_cache
from typing import Optional
from sentence_transformers import SentenceTransformer


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def get_sentence_model(model_name: Optional[str] = None) -> SentenceTransformer:
    name = model_name or DEFAULT_MODEL
    return SentenceTransformer(name)

