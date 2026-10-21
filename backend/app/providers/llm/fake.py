import json
import typing

from pydantic import BaseModel

from app.providers.base import LLMCaps, TextRequest, TextResult, Usage


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


class FakeLLM:
    caps = LLMCaps(structured="json_object")

    async def generate_text(self, req: TextRequest, ctx=None) -> TextResult:
        if req.response_schema is not None:
            payload = _minimal_dict(req.response_schema)
        else:
            payload = {"ok": True}
        text = json.dumps(payload)
        return TextResult(
            text=text,
            usage=Usage(input_tokens=0, output_tokens=len(text.split())),
            model="fake",
        )
