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
        [s.model_dump() for s in validated.scenes], format_slug=None
    )
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []
    assert len(validated.claims_to_verify) == 2


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
