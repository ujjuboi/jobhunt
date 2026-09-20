"""
Embedding client for JobHunt
Uses oMLX's /v1/embeddings API with BGE-M3 model
"""
import logging
import time
import random
from typing import List, Optional
from ..config import get_omlx_settings
from .. import llm
import httpx

logger = logging.getLogger(__name__)

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

MAX_EMBED_RETRIES = 3


def _retry_post(client: httpx.Client, url: str, *, headers: dict, json: dict) -> httpx.Response:
    """POST with a small retry loop for transient failures (timeout/5xx/429).

    Args:
        client: The HTTP client to post with.
        url: The endpoint URL.
        headers: Request headers.
        json: The JSON payload.

    Returns:
        The final :class:`httpx.Response`.

    Raises:
        httpx.HTTPError: When transport errors still occur after all retries.
    """
    attempts = 0
    while True:
        try:
            response = client.post(url, headers=headers, json=json)
            if response.status_code in llm.TRANSIENT_STATUS_CODES and attempts < MAX_EMBED_RETRIES:
                attempts += 1
                delay = 0.5 * (2 ** (attempts - 1)) + random.uniform(0, 0.1)
                logger.warning(
                    "Embedding API transient error %s; retry %d/%d in %.2fs",
                    response.status_code, attempts, MAX_EMBED_RETRIES, delay,
                )
                time.sleep(delay)
                continue
            return response
        except (httpx.TimeoutException, httpx.ConnectError) as error:
            if attempts >= MAX_EMBED_RETRIES:
                raise
            attempts += 1
            delay = 0.5 * (2 ** (attempts - 1)) + random.uniform(0, 0.1)
            logger.warning("Embedding API transport error %s; retry %d/%d in %.2fs",
                           error, attempts, MAX_EMBED_RETRIES, delay)
            time.sleep(delay)


class EmbeddingClient:
    """Client for interacting with oMLX embeddings API."""

    def __init__(self):
        settings = get_omlx_settings()
        self.base_url = settings.base_url
        self.api_key = settings.api_key
        self.client = httpx.Client(timeout=llm.DEFAULT_TIMEOUT_SECONDS)

    def embed_text(
        self,
        text: str,
        model: Optional[str] = None,
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

            response = _retry_post(
                self.client,
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or llm.get_default_model("embedding"),
                    "input": [payload],
                    "encoding_format": "float",
                },
            )

            if response.status_code == 200:
                data = response.json()
                embedding = data["data"][0]["embedding"]
                return self.normalize_embedding(embedding)
            else:
                logger.error("Embedding API error: %s - %s", response.status_code, response.text)
                return None

        except Exception as error:
            logger.warning("Error generating embedding: %s", error, exc_info=True)
            return None

    def embed_batch(
        self,
        texts: List[str],
        model: Optional[str] = None,
        use_bge_prefix: bool = False,
    ) -> Optional[List[List[float]]]:
        """Generate normalized embeddings for a batch of texts."""
        try:
            if use_bge_prefix:
                texts = [f"{BGE_QUERY_PREFIX}{t}" for t in texts]

            response = _retry_post(
                self.client,
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or llm.get_default_model("embedding"),
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
                logger.error("Batch embedding API error: %s - %s", response.status_code, response.text)
                return None

        except Exception as error:
            logger.warning("Error generating batch embeddings: %s", error, exc_info=True)
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
