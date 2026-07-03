"""
Провайдеро-агностичный слой эмбеддингов (docs/00 §10.2, ADR-007).
Один интерфейс EmbeddingProvider → две реализации:
  local  — sentence-transformers (без ключа; для прогона здесь). Дефолт multilingual-MiniLM.
  openai — OpenAI text-embedding-3-large (3072) для прода (нужен OPENAI_API_KEY).
Смена провайдера = смена профиля в конфиге, без изменения кода retrieval.
"""
from __future__ import annotations

import os
from typing import List, Protocol


class EmbeddingProvider(Protocol):
    dim: int
    name: str
    def embed_documents(self, texts: List[str]) -> List[List[float]]: ...
    def embed_query(self, text: str) -> List[float]: ...


class LocalEmbedder:
    """sentence-transformers, нормализованные вектора (косинус = dot). Без ключа."""

    def __init__(self, model: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        from sentence_transformers import SentenceTransformer

        self.model_name = model
        self.name = f"local:{model}"
        self._m = SentenceTransformer(model)
        self.dim = self._m.get_sentence_embedding_dimension()

    def embed_documents(self, texts):
        return self._m.encode(texts, normalize_embeddings=True, batch_size=32,
                              show_progress_bar=False, convert_to_numpy=True).tolist()

    def embed_query(self, text):
        return self._m.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0].tolist()


class OpenAIEmbedder:
    """OpenAI text-embedding-3-*. Прод-путь. Требует OPENAI_API_KEY."""

    def __init__(self, model: str = "text-embedding-3-large"):
        import openai

        self.client = openai.OpenAI()  # ключ из окружения OPENAI_API_KEY
        self.model_name = model
        self.name = f"openai:{model}"
        self.dim = 3072 if "large" in model else 1536

    def embed_documents(self, texts):
        out: list = []
        for i in range(0, len(texts), 128):
            resp = self.client.embeddings.create(model=self.model_name, input=texts[i:i + 128])
            out.extend(d.embedding for d in resp.data)
        return out

    def embed_query(self, text):
        return self.client.embeddings.create(model=self.model_name, input=[text]).data[0].embedding


def get_embedder(profile: str = "local", **kw) -> EmbeddingProvider:
    profile = (os.environ.get("EMBED_PROFILE") or profile).lower()
    if profile in ("openai", "cloud"):
        return OpenAIEmbedder(**kw)
    return LocalEmbedder(**kw)
