import faiss
import pickle
import numpy as np
import os
from pathlib import Path
from app.utils.embeddings import get_sentence_model, DEFAULT_MODEL
from app.utils.logging_config import get_logger

model = get_sentence_model(DEFAULT_MODEL)

def _resolve_faiss_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "faiss_index",  # /app/faiss_index
        Path.cwd() / "faiss_index",
        Path("/app/faiss_index"),
        Path("/faiss_index"),
    ]
    for p in candidates:
        if (p / "tables.index").exists() and (p / "columns.index").exists():
            return p
    raise FileNotFoundError(
        "FAISS index files not found. Ensure faiss_index/ is present in project root or rebuild via scripts/build_faiss_index.py"
    )

FAISS_DIR = _resolve_faiss_dir()
logger = get_logger(__name__)
logger.info("[SemanticSearch] Using FAISS dir: %s", FAISS_DIR)

table_index = faiss.read_index(str(FAISS_DIR / "tables.index"))
column_index = faiss.read_index(str(FAISS_DIR / "columns.index"))

with open(FAISS_DIR / "table_ids.pkl", "rb") as f:
    table_ids = pickle.load(f)
with open(FAISS_DIR / "column_ids.pkl", "rb") as f:
    column_ids = pickle.load(f)

def retrieve_tables(user_query: str, top_k: int = 3):
    vec = model.encode([user_query], normalize_embeddings=True)
    scores, indices = table_index.search(np.array(vec), top_k)
    return [table_ids[i] for i in indices[0]]

def retrieve_columns(user_query: str, top_k: int = 8):
    vec = model.encode([user_query], normalize_embeddings=True)
    scores, indices = column_index.search(np.array(vec), top_k)
    return [column_ids[i] for i in indices[0]]
