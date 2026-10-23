import json

from app.domain.llm_outputs import ScriptDraft, ValidationOutput
from app.domain.script_rules import run_checks, validate_script_draft
from app.providers.base import Message, TextRequest
from app.providers.llm.fake import FakeLLM


def script_messages(topic_sentence: str = "Idea title: Kenapa cicak bisa menempel di dinding") -> list[Message]:
    return [
        Message(
            role="user",
            content=(
                topic_sentence
                + '\n{"schema_version": "script.v1", "scenes": []}'
            ),
        )
    ]


async def test_fake_script_fixture_is_valid_and_clean():
    llm = FakeLLM()
    result = await llm.generate_text(
        TextRequest(messages=script_messages(), response_schema=ScriptDraft)
    )
    draft = ScriptDraft.model_validate(json.loads(result.text))
    validated = validate_script_draft(draft)
    assert len(validated.scenes) == 10
    assert validated.hook == validated.scenes[0].voiceover
    issues = run_checks(
        [s.model_dump() for s in validated.scenes],
        format_slug=None,
        title=validated.title,
    )
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []
    assert len(validated.claims_to_verify) == 2
    # Fase 9: sebagian besar scene membawa keyword_text visual
    with_keyword = [s for s in validated.scenes if s.keyword_text]
    assert len(with_keyword) >= 7
    assert validated.scenes[0].keyword_text


async def test_fake_script_fixture_politics_has_impact_chain():
    llm = FakeLLM()
    messages = script_messages(
        "Idea title: Kenapa cicak bisa menempel di dinding\n"
        "Category: Politik & Kebijakan"
    )
    result = await llm.generate_text(
        TextRequest(messages=messages, response_schema=ScriptDraft)
    )
    draft = ScriptDraft.model_validate(json.loads(result.text))
    validated = validate_script_draft(draft)
    beats = [s.beat for s in validated.scenes]
    assert beats.count("impact") == 2
    first_main = beats.index("main")
    assert all(i > first_main for i, b in enumerate(beats) if b == "impact")
    assert beats[-1] == "cta"
    assert all(i < len(beats) - 1 for i, b in enumerate(beats) if b == "impact")
    issues = run_checks(
        [s.model_dump() for s in validated.scenes],
        format_slug=None,
        category_slug="politics",
        title=validated.title,
    )
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []


async def test_fake_validation_fixture_passes():
    llm = FakeLLM()
    request = TextRequest(
        messages=[
            Message(
                role="user",
                content='{"status": "PASS", "score": 0, "summary": "", "issues": []}',
            )
        ],
        response_schema=ValidationOutput,
    )
    result = await llm.generate_text(request)
    output = ValidationOutput.model_validate(json.loads(result.text))
    assert output.status == "PASS"
    assert output.score == 85
    assert all(issue.severity != "error" for issue in output.issues)
