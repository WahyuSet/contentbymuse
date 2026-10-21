import httpx
import pytest
import respx

from app.providers.base import Message, TextRequest
from app.providers.errors import AuthError, RateLimitError, ServerError
from app.providers.llm.openai_compatible import OpenAICompatibleLLM

URL = "http://llm.test/v1/chat/completions"


def make_llm(**kw):
    return OpenAICompatibleLLM(
        base_url="http://llm.test/v1", api_key="kunci", default_model="m1", **kw
    )


@respx.mock
async def test_generate_text_json_object_and_system_merge():
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 5},
                "model": "m1",
            },
        )
    )
    llm = make_llm(quirks={"system_role": False, "structured": "json_object"})
    result = await llm.generate_text(
        TextRequest(
            messages=[
                Message(role="system", content="Aturan utama."),
                Message(role="user", content="Halo"),
            ]
        ),
        None,
    )
    assert result.text == '{"ok": true}'
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 11
    body = route.calls[0].request.read()
    assert b'"response_format":{"type":"json_object"}' in body
    assert b"Aturan utama." in body
    assert body.count(b'"role":"system"') == 0


@respx.mock
async def test_no_response_format_when_structured_none():
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )
    )
    llm = make_llm(quirks={"structured": "none"})
    await llm.generate_text(
        TextRequest(messages=[Message(role="user", content="x")]), None
    )
    assert b"response_format" not in route.calls[0].request.read()


@respx.mock
async def test_http_errors_map_to_provider_errors():
    respx.post(URL).mock(return_value=httpx.Response(401, text="ditolak"))
    with pytest.raises(AuthError) as exc:
        await make_llm().generate_text(
            TextRequest(messages=[Message(role="user", content="x")]), None
        )
    assert exc.value.retryable is False
    assert exc.value.message_id

    respx.post(URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"}, text="pelan")
    )
    with pytest.raises(RateLimitError) as exc:
        await make_llm().generate_text(
            TextRequest(messages=[Message(role="user", content="x")]), None
        )
    assert exc.value.retry_after == 7

    respx.post(URL).mock(return_value=httpx.Response(503, text="rusak"))
    with pytest.raises(ServerError):
        await make_llm().generate_text(
            TextRequest(messages=[Message(role="user", content="x")]), None
        )
