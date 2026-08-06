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
