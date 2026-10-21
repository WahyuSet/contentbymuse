import json

import pytest

from app.db.models import Provider
from app.domain.llm_outputs import IdeasOutput
from app.providers.base import LLMCaps, TextResult
from app.providers.errors import MalformedOutputError
from app.services.prompts import PromptService, sync_prompts
from app.services.structured_llm import StructuredLLM, clean_json_text, validate_ideas


def idea(i: int, **over) -> dict:
    base = {
        "title": f"Kenapa benda ke-{i} berperilaku sangat aneh sekali",
        "angle": f"Penjelasan konkret nomor {i} tentang perilaku benda itu",
        "hook": f"Kamu pasti tidak menyangka benda ke-{i} ini bisa begini",
        "why_it_works": "Dekat dengan keseharian penonton",
        "fact_risk": "low",
        "fact_note": None,
    }
    base.update(over)
    return base


def payload(n=8, **kw) -> dict:
    return {"suggested_category": "animals", "ideas": [idea(i + 1, **kw) for i in range(n)]}


class StubLLM:
    caps = LLMCaps(structured="json_object")

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    async def generate_text(self, req, ctx=None):
        self.requests.append(req)
        return self.replies.pop(0)


def ok_reply(obj, finish="stop") -> TextResult:
    return TextResult(text=json.dumps(obj), model="stub", finish_reason=finish)


async def make_service(session, stubs):
    await sync_prompts(session)
    await session.commit()
    pairs = []
    for i, stub in enumerate(stubs):
        provider = Provider(name=f"Stub {i}", capability="llm", adapter="fake")
        session.add(provider)
        await session.flush()
        pairs.append((provider, stub))
    return StructuredLLM(pairs, PromptService(session))


def test_clean_json_text_strips_think_fence_and_trailing_comma():
    raw = '<think>mikIr dulu</think>```json\n{"a": 1, "b": [1, 2,],}\n```'
    assert json.loads(clean_json_text(raw)) == {"a": 1, "b": [1, 2]}


def test_clean_json_text_takes_outermost_object():
    raw = 'pembuka {"a": {"x": 1}} penutup'
    assert json.loads(clean_json_text(raw)) == {"a": {"x": 1}}


def test_validate_ideas_requires_exactly_eight():
    validate_ideas(IdeasOutput.model_validate(payload()), {"animals"})
    with pytest.raises(ValueError, match="tepat 8"):
        validate_ideas(IdeasOutput.model_validate(payload(n=7)), {"animals"})


def test_validate_ideas_bad_slug_becomes_none_and_check_needs_note():
    out = IdeasOutput.model_validate({**payload(), "suggested_category": "tidak-ada"})
    validated = validate_ideas(out, {"animals"})
    assert validated.suggested_category is None
    bad = IdeasOutput.model_validate(payload())
    bad.ideas[0].fact_risk = "check"
    bad.ideas[0].fact_note = None
    with pytest.raises(ValueError, match="fact_note"):
        validate_ideas(bad, {"animals"})


def test_validate_ideas_strips_angle_prefix():
    out = IdeasOutput.model_validate(payload())
    out.ideas[0].angle = "Hidden logic: cicak memakai gaya van der Waals"
    validated = validate_ideas(out, {"animals"})
    assert validated.ideas[0].angle.startswith("cicak memakai")


async def test_retry_with_error_feedback_then_success(session):
    stub = StubLLM([TextResult(text="{rusak", model="stub"), ok_reply(payload())])
    service = await make_service(session, [stub])
    result = await service.generate(
        task="ideas.from_topic",
        inputs={"topic": "cicak", "language": "id-ID", "category": None, "format": None},
        output_model=IdeasOutput,
        validate=lambda out: validate_ideas(out, {"animals"}),
    )
    assert isinstance(result.data, IdeasOutput)
    assert len(stub.requests) == 2
    feedback = stub.requests[1].messages[-1]
    assert feedback.role == "user" and "tidak valid" in feedback.content


async def test_malformed_falls_through_to_next_candidate(session):
    bad = StubLLM([TextResult(text="bukan json", model="stub")] * 2)
    good = StubLLM([ok_reply(payload())])
    service = await make_service(session, [bad, good])
    result = await service.generate(
        task="ideas.from_topic",
        inputs={"topic": "cicak", "language": "id-ID", "category": None, "format": None},
        output_model=IdeasOutput,
        validate=lambda out: validate_ideas(out, {"animals"}),
    )
    assert result.provider.name == "Stub 1"
    assert len(good.requests) == 1


async def test_all_candidates_malformed_raises(session):
    bad = StubLLM([TextResult(text="zzz", model="stub")] * 2)
    service = await make_service(session, [bad])
    with pytest.raises(MalformedOutputError):
        await service.generate(
            task="ideas.from_topic",
            inputs={"topic": "cicak", "language": "id-ID", "category": None, "format": None},
            output_model=IdeasOutput,
            validate=lambda out: validate_ideas(out, {"animals"}),
        )


async def test_truncated_reply_retried_with_more_tokens(session):
    truncated = TextResult(text='{"suggested_category": "animals", "ideas": [', model="stub", finish_reason="length")
    stub = StubLLM([truncated, ok_reply(payload())])
    service = await make_service(session, [stub])
    result = await service.generate(
        task="ideas.from_topic",
        inputs={"topic": "cicak", "language": "id-ID", "category": None, "format": None},
        output_model=IdeasOutput,
        validate=lambda out: validate_ideas(out, {"animals"}),
    )
    assert isinstance(result.data, IdeasOutput)
    first, second = stub.requests[0], stub.requests[1]
    assert second.max_tokens == min(first.max_tokens * 2, 16000)
