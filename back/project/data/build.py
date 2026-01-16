import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
CHUNKS_PATH = "chunks.json"
INDEX_PATH = "faiss_index.bin"

# 1. Модель эмбеддингов
model = SentenceTransformer(MODEL_NAME)

# 2. Загружаем чанки
with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)
    chunks = data["chunks"]

texts = [c["content"] for c in chunks]

# 3. Строим эмбеддинги
embeddings = model.encode(
    texts,
    normalize_embeddings=True,
    convert_to_numpy=True
).astype("float32")

dim = embeddings.shape[1]
print("Embedding dim:", dim)

# 4. FAISS index (cosine similarity)
index = faiss.IndexFlatIP(dim)
index.add(embeddings)

# 5. Сохраняем индекс
faiss.write_index(index, INDEX_PATH)

print("FAISS index saved:", INDEX_PATH)
