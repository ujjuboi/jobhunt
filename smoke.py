#!/usr/bin/env python3
"""
Smoke test to verify oMLX integration works.
Checks: models list, embeddings round-trip, tool-call round-trip,
structured JSON (response_format=json_object).
"""
import json

from openai import OpenAI

from jobhunt.config import load_omlx_settings

CHAT_MODEL = "Qwen3-30B-A3B-6bit"
EMBEDDING_MODEL = "bge-m3-mlx-fp16"

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
}


def test_models(client: OpenAI) -> None:
    models = client.models.list()
    ids = [m.id for m in models.data]
    print(f"✓ Models endpoint reachable ({len(ids)} models)")
    for model_id in ids:
        print(f"  - {model_id}")


def test_embeddings(client: OpenAI) -> None:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input="Test embedding text")
    dims = len(response.data[0].embedding)
    print(f"✓ Embeddings round-trip ({dims} dims)")
    if dims <= 0:
        raise AssertionError("embedding has no dimensions")


def test_tool_call_round_trip(client: OpenAI) -> None:
    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "user", "content": "What is the weather in San Francisco? Call the get_weather tool."}
        ],
        tools=[WEATHER_TOOL],
        tool_choice="auto",
        temperature=0.1,
    )
    message = completion.choices[0].message
    if not message.tool_calls:
        raise AssertionError("expected a tool_call but none was returned")
    for call in message.tool_calls:
        args = json.loads(call.function.arguments)
        print(f"✓ Tool-call round-trip ({call.function.name}: {args})")


def test_structured_json(client: OpenAI) -> None:
    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "user", "content": "List three colors. Respond as JSON with a 'colors' array."}
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    parsed = json.loads(completion.choices[0].message.content)
    if not isinstance(parsed.get("colors"), list):
        raise AssertionError(f"expected a 'colors' list in structured JSON response, got: {parsed}")
    print(f"✓ Structured JSON response (colors: {parsed['colors']})")


def test_omlx_connection() -> bool:
    settings = load_omlx_settings()
    print(f"Testing connection to oMLX at {settings.base_url} (API key redacted)")

    client = OpenAI(base_url=settings.base_url, api_key=settings.api_key)

    test_models(client)
    test_embeddings(client)
    test_tool_call_round_trip(client)
    test_structured_json(client)
    return True


if __name__ == "__main__":
    try:
        success = test_omlx_connection()
    except Exception as e:
        print(f"✗ Error testing oMLX connection: {e}")
        success = False

    if success:
        print("\n✓ All oMLX smoke tests passed!")
    else:
        print("\n✗ Some oMLX smoke tests failed!")
        raise SystemExit(1)
