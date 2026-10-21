import time

import httpx

from app.providers.base import LLMCaps, TextRequest, TextResult, Usage
from app.providers.errors import (
    AuthError,
    BadRequestError,
    ContentPolicyError,
    ProviderTimeout,
    RateLimitError,
    ServerError,
)


class OpenAICompatibleLLM:
    """Adapter LLM untuk endpoint serasi OpenAI `POST /chat/completions` (Spec §5.3, §5.4)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        default_model: str | None,
        quirks: dict | None = None,
    ):
        quirks = quirks or {}
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model
        self._system_role = quirks.get("system_role", True)
        self._timeout_s = float(quirks.get("timeout_s", 120))
        self._retry_safe = bool(quirks.get("retry_safe", True))
        self._extra_body = quirks.get("extra_body") or {}
        self.caps = LLMCaps(structured=str(quirks.get("structured", "json_object")))

    def _messages(self, req: TextRequest) -> list[dict]:
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        if not self._system_role:
            system_text = "\n\n".join(
                m["content"] for m in messages if m["role"] == "system"
            )
            messages = [m for m in messages if m["role"] != "system"]
            if system_text:
                if messages:
                    messages[0]["content"] = f"{system_text}\n\n{messages[0]['content']}"
                else:
                    messages = [{"role": "user", "content": system_text}]
        return messages

    async def generate_text(self, req: TextRequest, ctx=None) -> TextResult:
        body: dict = {
            "model": req.model or self._default_model,
            "messages": self._messages(req),
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if self.caps.structured == "json_object":
            body["response_format"] = {"type": "json_object"}
        elif self.caps.structured == "json_schema" and req.response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": req.response_schema.__name__,
                    "schema": req.response_schema.model_json_schema(),
                },
            }
        body.update(self._extra_body)
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        started = time.monotonic()
        try:
            # trust_env=False: proxy dari environment tidak boleh membelokkan
            # panggilan ke endpoint provider yang dikonfigurasi pemilik.
            async with httpx.AsyncClient(timeout=self._timeout_s, trust_env=False) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions", json=body, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(detail=str(exc), retryable=self._retry_safe) from exc
        except httpx.HTTPError as exc:
            raise ServerError(detail=str(exc)) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            raise self._map_error(response)
        payload = response.json()
        choice = payload["choices"][0]
        usage = payload.get("usage") or {}
        return TextResult(
            text=choice["message"]["content"],
            usage=Usage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            ),
            model=payload.get("model") or body["model"] or "",
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
        )

    @staticmethod
    def _map_error(response: httpx.Response) -> Exception:
        detail = response.text
        status = response.status_code
        if status in (401, 403):
            return AuthError(detail=detail)
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            return RateLimitError(
                detail=detail,
                retry_after=float(retry_after) if retry_after else None,
            )
        if status == 400 and (
            "content_policy" in detail or "content policy" in detail.lower()
        ):
            return ContentPolicyError(detail=detail)
        if status in (400, 404, 422):
            return BadRequestError(detail=detail)
        return ServerError(detail=detail)
