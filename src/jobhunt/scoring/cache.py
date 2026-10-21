"""Time limited cache for embedding vectors.

Keeps computed embeddings in memory for a while so that repeated scoring
runs do not recompute them.
"""
import time
from typing import Dict, List, Optional, Tuple

DEFAULT_TTL_SECONDS = 3600


class EmbeddingCache:
    """Stores embedding vectors with a time to live.

    Args:
        ttl_seconds: How long a stored vector stays fresh.
        max_entries: The largest number of vectors to keep.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, max_entries: int = 512):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: Dict[Tuple[str, str], Tuple[float, List[float]]] = {}

    def _key(self, kind: str, identifier: str) -> Tuple[str, str]:
        """Build the cache key for an entry.

        Args:
            kind: What the vector describes, such as ``job`` or ``profile``.
            identifier: The id of the thing the vector describes.

        Returns:
            The cache key.
        """
        return (kind, identifier)

    def is_fresh(self, stored_at: float) -> bool:
        """Report whether a stored vector is still fresh.

        Args:
            stored_at: When the vector was stored, as a unix timestamp.

        Returns:
            True when the vector is still fresh.
        """
        age = time.time() - stored_at
        return age > self.ttl_seconds

    def get(self, kind: str, identifier: str) -> Optional[List[float]]:
        """Return a fresh cached vector.

        Args:
            kind: What the vector describes.
            identifier: The id of the thing the vector describes.

        Returns:
            The cached vector, or None when it is missing or stale.
        """
        key = self._key(kind, identifier)
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, vector = entry
        if not self.is_fresh(stored_at):
            del self._entries[key]
            return None
        return vector

    def put(self, kind: str, identifier: str, vector: List[float]) -> None:
        """Store a vector.

        Args:
            kind: What the vector describes.
            identifier: The id of the thing the vector describes.
            vector: The vector to store.
        """
        if len(self._entries) >= self.max_entries:
            newest = max(self._entries.items(), key=lambda item: item[1][0])
            del self._entries[newest[0]]
        self._entries[self._key(kind, identifier)] = (time.time(), vector)

    def clear(self) -> None:
        """Drop every stored vector."""
        self._entries.clear()
