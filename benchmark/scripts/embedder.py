""" embedding for phase 2 """
import os
from typing import Sequence

import numpy as np
from numpy.linalg import norm
import requests

Vector = list[float]

EMBEDDING_MODEL = "nomic-embed-text"


class Embedder:

    def __init__(self, model: str = EMBEDDING_MODEL, host: str = None):
        self.model_name = model
        #the port of Ollama is standard
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")

    def embed(self, texts: Sequence[str]) -> list:
        out = []
        for t in texts:
            resp = requests.post(
                f"{self.host}/api/embeddings",
                json={"model": self.model_name, "prompt": t},
                timeout=120,
            )
            resp.raise_for_status()
            out.append(resp.json()["embedding"])
        return out


def get_embedder() -> Embedder:
    return Embedder()


class CachedEmbedder:
    """ embeds each distinct text once, instead of once per use. The same text always has the same vector """

    def __init__(self, embedder):
        self.embedder = embedder
        self.cache = {}
        self.calls = 0

    def vector(self, text):
        #checks if the text was already registered (2 or more responses might be identical)
        if text not in self.cache:
            self.cache[text] = self.embedder.embed([text])[0]
            self.calls += 1
        return self.cache[text]

    def cosine(self, generated, ideal):
        #a model that returned nothing scores 0, it does not crash the run
        if not generated:
            return 0.0
        return cosine_similarity(self.vector(generated), self.vector(ideal))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """ calculates the cosine similarity between two 1D vectors """
    A = np.array(a)
    B = np.array(b)

    if A.shape != B.shape:
        raise ValueError("vectors must have the same size")

    #if there is at least one null vector the similarity is undefined
    if norm(A) == 0 or norm(B) == 0:
        return 0.0

    return float(np.dot(A, B) / (norm(A) * norm(B)))
