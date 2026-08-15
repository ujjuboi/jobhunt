"""
EmbeddingClient tests: BGE prefix handling, index ordering, normalization.
oMLX HTTP is mocked; get_omlx_settings is stubbed.
"""
from types import SimpleNamespace

from jobhunt.embeddings import EmbeddingClient, BGE_QUERY_PREFIX


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.last_json = None

    def post(self, url, **kwargs):
        self.last_json = kwargs["json"]
        return self.response

    def close(self):
        pass


def _make_client(monkeypatch):
    settings = SimpleNamespace(base_url="http://test/v1", api_key="k")
    monkeypatch.setattr("jobhunt.embeddings.get_omlx_settings", lambda: settings)
    client = EmbeddingClient()
    fake_http = FakeClient(FakeResponse({"data": [{"index": 0, "embedding": [1.0, 0.0]}]}))
    client.client = fake_http
    return client, fake_http


def test_embed_text_uses_prefix_only_when_requested(monkeypatch):
    client, fake = _make_client(monkeypatch)
    client.embed_text("senior engineer", use_bge_prefix=True)
    assert fake.last_json["input"] == [f"{BGE_QUERY_PREFIX}senior engineer"]


def test_embed_text_no_prefix_by_default(monkeypatch):
    client, fake = _make_client(monkeypatch)
    text = "Full-stack engineer with 5 years of Python, React, and AWS experience. "
    client.embed_text(text * 10)
    assert fake.last_json["input"] == [text * 10]


def test_embed_text_returns_normalized_vector(monkeypatch):
    client, fake = _make_client(monkeypatch)
    fake.response = FakeResponse({"data": [{"index": 0, "embedding": [3.0, 0.0]}]})
    vec = client.embed_text("x")
    assert vec == [1.0, 0.0]


def test_embed_batch_orders_by_index(monkeypatch):
    client, fake = _make_client(monkeypatch)
    fake.response = FakeResponse(
        {
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ]
        }
    )
    vecs = client.embed_batch(["a", "b"])
    assert vecs == [[1.0, 0.0], [0.0, 1.0]]


def test_embed_batch_prefix_applied_to_all(monkeypatch):
    client, fake = _make_client(monkeypatch)
    client.embed_batch(["a", "b"], use_bge_prefix=True)
    assert fake.last_json["input"] == [f"{BGE_QUERY_PREFIX}a", f"{BGE_QUERY_PREFIX}b"]


def test_embed_text_error_returns_none(monkeypatch):
    client, fake = _make_client(monkeypatch)
    fake.response = FakeResponse({"error": "boom"}, status_code=500)
    assert client.embed_text("x") is None
