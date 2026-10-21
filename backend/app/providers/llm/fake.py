import json
import re
import typing

from pydantic import BaseModel

from app.providers.base import LLMCaps, TextRequest, TextResult, Usage

_QUESTION_LEAD = re.compile(
    r"^(kenapa|mengapa|apa|bagaimana|kenalkah|tahukah kamu)\s+", flags=re.IGNORECASE
)


def _minimal_value(annotation) -> object:
    origin = typing.get_origin(annotation)
    if origin is list:
        return []
    if origin is dict:
        return {}
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _minimal_dict(annotation)
    return None


def _minimal_dict(schema: type[BaseModel]) -> dict:
    return {name: _minimal_value(field.annotation) for name, field in schema.model_fields.items()}


def _topic_core(messages) -> str:
    for message in messages:
        for line in message.content.splitlines():
            if line.strip().lower().startswith("topik:"):
                topic = line.split(":", 1)[1].strip().rstrip(".")
                topic = _QUESTION_LEAD.sub("", topic)
                words = topic.split()
                return " ".join(words[:6]) or "topik ini"
    return "topik ini"


def _ideas_fixture(messages) -> dict:
    core = _topic_core(messages)
    cap = core[:1].upper() + core[1:]
    frames = [
        (f"Kenapa {core} bisa terjadi begitu saja?", "low", None),
        (f"Apa yang sebenarnya terjadi di balik {core}?", "low", None),
        (f"{cap}: fakta yang jarang dibahas orang", "low", None),
        (
            f"Mitos atau fakta soal {core}? Kita periksa",
            "check",
            f"Sebagian kepercayaan soal {core} belum diuji dengan data yang kuat.",
        ),
        (f"Apa jadinya kalau {core} berhenti terjadi?", "low", None),
        (
            f"Rahasia kecil di balik {core} yang mengejutkan",
            "check",
            f"Penjelasan populer soal {core} masih menyisakan bagian yang belum pasti.",
        ),
        (f"Kenapa tidak semua orang sadar soal {core} ini?", "low", None),
        (f"{cap} dan hal-hal aneh yang menyertainya", "low", None),
    ]
    ideas = []
    for i, (title, risk, note) in enumerate(frames, start=1):
        ideas.append(
            {
                "title": title,
                "angle": f"Penjelasan konkret nomor {i} tentang {core}, dari sebab sampai akibatnya",
                "hook": f"Berhenti scroll sebentar, {core} ternyata tidak sesederhana itu",
                "why_it_works": "Dekat dengan pengalaman penonton sehari-hari",
                "fact_risk": risk,
                "fact_note": note,
            }
        )
    return {"suggested_category": "animals", "ideas": ideas}


class FakeLLM:
    caps = LLMCaps(structured="json_object")

    async def generate_text(self, req: TextRequest, ctx=None) -> TextResult:
        joined = "\n".join(m.content for m in req.messages)
        if "suggested_category" in joined:
            # Mode json_object tidak mengirim schema; kontrak di prompt adalah penandanya.
            payload = _ideas_fixture(req.messages)
        elif req.response_schema is not None:
            payload = _minimal_dict(req.response_schema)
        else:
            payload = {"ok": True}
        text = json.dumps(payload)
        return TextResult(
            text=text,
            usage=Usage(input_tokens=0, output_tokens=len(text.split())),
            model="fake",
        )
