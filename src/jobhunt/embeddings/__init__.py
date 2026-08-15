"""
Embedding client for JobHunt
Uses oMLX's /v1/embeddings API with BGE-M3 model
"""
from typing import List, Optional
from ..config import get_omlx_settings
import httpx

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingClient:
    """Client for interacting with oMLX embeddings API."""

    def __init__(self):
        settings = get_omlx_settings()
        self.base_url = settings.base_url
        self.api_key = settings.api_key
        self.client = httpx.Client()

    def embed_text(
        self,
        text: str,
        model: str = "bge-m3-mlx-fp16",
        use_bge_prefix: bool = False,
    ) -> Optional[List[float]]:
        """Generate a normalized embedding for a single text.

        use_bge_prefix applies the BGE query instruction prefix, which should be
        used for short/query-side text (profile, resume) but not for plain
        documents such as job descriptions.
        """
        try:
            payload = text
            if use_bge_prefix:
                payload = f"{BGE_QUERY_PREFIX}{text}"

            response = self.client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": [payload],
                    "encoding_format": "float",
                },
            )

            if response.status_code == 200:
                data = response.json()
                embedding = data["data"][0]["embedding"]
                return self.normalize_embedding(embedding)
            else:
                print(f"Embedding API error: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None

    def embed_batch(
        self,
        texts: List[str],
        model: str = "bge-m3-mlx-fp16",
        use_bge_prefix: bool = False,
    ) -> Optional[List[List[float]]]:
        """Generate normalized embeddings for a batch of texts."""
        try:
            if use_bge_prefix:
                texts = [f"{BGE_QUERY_PREFIX}{t}" for t in texts]

            response = self.client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": texts,
                    "encoding_format": "float",
                },
            )

            if response.status_code == 200:
                data = response.json()
                # The API keys items by index; ordering is not guaranteed.
                items = sorted(data["data"], key=lambda item: item.get("index", 0))
                embeddings = [item["embedding"] for item in items]
                return [self.normalize_embedding(v) for v in embeddings]
            else:
                print(f"Batch embedding API error: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"Error generating batch embeddings: {e}")
            return None

    def normalize_embedding(self, embedding: List[float]) -> List[float]:
        """Normalize embedding to unit vector."""
        import numpy as np

        arr = np.array(embedding, dtype=float)
        norm = np.linalg.norm(arr)
        if norm > 0:
            return (arr / norm).tolist()
        return embedding

    def close(self):
        """Close the HTTP client."""
        self.client.close()
