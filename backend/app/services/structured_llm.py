import json
import re
from dataclasses import dataclass

from pydantic import BaseModel

from app.db.models import Provider
from app.domain.llm_outputs import IdeasOutput
from app.providers.base import Message, TextRequest, Usage
from app.providers.errors import MalformedOutputError
from app.services.prompts import PromptService, RenderedPrompt

_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_BAD_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')
ANGLE_PREFIXES = ("hidden logic", "curiosity gap", "secret mechanism", "mekanisme rahasia")


def clean_json_text(raw: str) -> str:
    """Bersihkan balasan model menjadi teks JSON (port aturan v1, Spec §5.2)."""
    text = _THINK_RE.sub("", raw).strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                text = text[start : i + 1]
                break
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    text = _BAD_ESCAPE_RE.sub(r"\\\\", text)
    return text


def _tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def validate_ideas(output: IdeasOutput, valid_category_slugs: set[str]) -> IdeasOutput:
    """Aturan bisnis ide (Spec §3.1). Melempar ValueError berpesan spesifik."""
    if len(output.ideas) != 8:
        raise ValueError(f"Wajib tepat 8 ide, diterima {len(output.ideas)}.")
    for item in output.ideas:
        item.title = item.title.strip()
    for i, first in enumerate(output.ideas):
        for second in output.ideas[i + 1 :]:
            a, b = _tokens(first.title), _tokens(second.title)
            union = a | b
            if union and len(a & b) / len(union) >= 0.8:
                raise ValueError(
                    f"Judul terlalu mirip satu sama lain: '{first.title}' dan '{second.title}'. "
                    "Buat judul yang jelas berbeda."
                )
    if output.suggested_category not in valid_category_slugs:
        output.suggested_category = None
    for item in output.ideas:
        lowered = item.angle.lstrip().lower()
        for prefix in ANGLE_PREFIXES:
            if lowered.startswith(prefix + ":"):
                item.angle = item.angle.lstrip()[len(prefix) + 1 :].lstrip()
                break
        if item.fact_risk == "check":
            if not (item.fact_note and item.fact_note.strip()):
                raise ValueError(
                    f"Ide '{item.title}' berstatus fact_risk=check tetapi fact_note kosong. "
                    "Isi fact_note satu kalimat tentang apa yang belum pasti."
                )
        else:
            item.fact_note = None
    return output


@dataclass
class StructuredResult:
    data: BaseModel
    provider: Provider
    model: str
    prompt_version_id: str
    raw_text: str
    prompt_text: str
    attempts: int
    usage: Usage


class StructuredLLM:
    """Render → panggil → parse → validasi → retry → provider berikutnya (Spec §5.2)."""

    def __init__(
        self,
        candidates: list[tuple[Provider, object]],
        prompts: PromptService,
    ):
        self._candidates = candidates
        self._prompts = prompts

    async def generate(
        self,
        *,
        task: str,
        inputs: dict,
        output_model: type[BaseModel],
        ctx=None,
        validate=None,
    ) -> StructuredResult:
        rendered: RenderedPrompt = await self._prompts.render(task, inputs)
        prompt_text = "\n\n".join(m.content for m in rendered.messages)
        last_error: MalformedOutputError | None = None
        for provider, adapter in self._candidates:
            attempts = 0
            messages = list(rendered.messages)
            max_tokens = rendered.max_tokens
            feedback_used = False
            truncated_retried = False
            while True:
                req = TextRequest(
                    messages=messages,
                    temperature=rendered.temperature,
                    max_tokens=max_tokens,
                    response_schema=(
                        output_model
                        if getattr(adapter.caps, "structured", "none") == "json_schema"
                        else None
                    ),
                )
                result = await adapter.generate_text(req, ctx)
                attempts += 1
                if result.finish_reason == "length" and not truncated_retried:
                    truncated_retried = True
                    max_tokens = min(max_tokens * 2, 16000)
                    messages = messages + [
                        Message(
                            role="user",
                            content=(
                                "Balasan sebelumnya terpotong. Kirim ulang jawaban "
                                "lengkap sesuai kontrak, tanpa teks lain."
                            ),
                        )
                    ]
                    continue
                try:
                    parsed = json.loads(clean_json_text(result.text))
                    data = output_model.model_validate(parsed)
                    if validate is not None:
                        validated = validate(data)
                        if validated is not None:
                            data = validated
                except Exception as exc:  # noqa: BLE001 — parse/validasi apa pun gagal = malformed (§5.2)
                    if not feedback_used:
                        feedback_used = True
                        messages = messages + [
                            Message(role="assistant", content=result.text[:4000]),
                            Message(
                                role="user",
                                content=(
                                    f"Jawaban tidak valid: {exc}. Perbaiki dan kirim "
                                    "ulang JSON lengkap sesuai kontrak, tanpa teks lain."
                                ),
                            ),
                        ]
                        continue
                    last_error = MalformedOutputError(detail=str(exc)[:500])
                    break
                return StructuredResult(
                    data=data,
                    provider=provider,
                    model=result.model,
                    prompt_version_id=rendered.version_id,
                    raw_text=result.text,
                    prompt_text=prompt_text,
                    attempts=attempts,
                    usage=result.usage,
                )
        raise last_error or MalformedOutputError(
            detail="Tidak ada kandidat provider LLM."
        )
