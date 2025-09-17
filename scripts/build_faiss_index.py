import json
import faiss
import os
from sentence_transformers import SentenceTransformer
import numpy as np
import pickle

# Load schema metadata using absolute path
schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "schema_metadata.json")
with open(schema_path, encoding="utf-8") as f:
    metadata = json.load(f)
# with open("data/schema_metadata.json", encoding="utf-8") as f:
#     metadata = json.load(f)

model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

table_texts = []
table_ids = []

column_texts = []
column_ids = []

for table, info in metadata.items():
    table_texts.append(info["description"])
    table_ids.append(table)

    for col, col_desc in info["columns"].items():
        full_id = f"{table}.{col}"
        column_texts.append(f"{col_desc} ({full_id})")
        column_ids.append(full_id)

# Encode
table_vecs = model.encode(table_texts, normalize_embeddings=True)
column_vecs = model.encode(column_texts, normalize_embeddings=True)

# Build FAISS index
table_index = faiss.IndexFlatIP(table_vecs.shape[1])
table_index.add(np.array(table_vecs))

column_index = faiss.IndexFlatIP(column_vecs.shape[1])
column_index.add(np.array(column_vecs))

# Save
os.makedirs("faiss_index", exist_ok=True)
faiss.write_index(table_index, "faiss_index/tables.index")
faiss.write_index(column_index, "faiss_index/columns.index")
with open("faiss_index/table_ids.pkl", "wb") as f:
    pickle.dump(table_ids, f)
with open("faiss_index/column_ids.pkl", "wb") as f:
    pickle.dump(column_ids, f)

print("FAISS index built successfully.")
