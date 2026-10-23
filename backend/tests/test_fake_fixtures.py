import json

from app.domain.llm_outputs import MetadataOutput, ScriptDraft, ValidationOutput
from app.domain.script_rules import run_checks, validate_script_draft
from app.providers.base import Message, TextRequest
from app.providers.llm.fake import FakeLLM, _wants_politics


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


# --- Fase 10 T6: fixture politik selaras twist + CTA biner ---


async def test_fake_script_fixture_politics_twist_and_binary_cta():
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
    assert beats == [
        "hook", "setup", "main", "main", "main",
        "twist", "impact", "impact", "payoff", "cta",
    ]
    issues = run_checks(
        [s.model_dump() for s in validated.scenes],
        format_slug=None,
        category_slug="politics",
        title=validated.title,
    )
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []
    assert [i for i in issues if i.code == "fairness_marker"] == []


async def test_fake_script_fixture_non_politics_unchanged():
    llm = FakeLLM()
    result = await llm.generate_text(
        TextRequest(messages=script_messages(), response_schema=ScriptDraft)
    )
    draft = ScriptDraft.model_validate(json.loads(result.text))
    validated = validate_script_draft(draft)
    beats = [s.beat for s in validated.scenes]
    assert beats == [
        "hook", "setup", "main", "main", "main", "main",
        "main", "main", "payoff", "cta",
    ]
    assert "twist" not in beats
    # Baris cta non-politik tetap yang lama persis.
    assert validated.scenes[-1].voiceover == (
        "Pernah mengalami hal serupa di rumah atau sekitarmu"
    )
    issues = run_checks(
        [s.model_dump() for s in validated.scenes],
        format_slug=None,
        title=validated.title,
    )
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []


def test_wants_politics_fix_flow_triggers():
    # Alur fix: issues dari run_checks Fase 10 memicu fixture politik.
    assert _wants_politics(
        [Message(role="user", content='Issues: [{"code": "twist_structure"}]')]
    )
    assert _wants_politics(
        [Message(role="user", content='Issues: [{"code": "binary_cta"}]')]
    )
    # Draf yang diperbaiki sudah membawa beat twist (JSON).
    assert _wants_politics(
        [Message(role="user", content='Draft: {"beat": "twist", "voiceover": "..."}')]
    )


async def test_fake_script_fixture_fix_flow_twist_issue_uses_politics():
    llm = FakeLLM()
    messages = script_messages(
        "Idea title: Kenapa cicak bisa menempel di dinding\n"
        'Issues: [{"code": "twist_structure", "severity": "error"}]'
    )
    result = await llm.generate_text(
        TextRequest(messages=messages, response_schema=ScriptDraft)
    )
    draft = ScriptDraft.model_validate(json.loads(result.text))
    beats = [s.beat for s in draft.scenes]
    assert beats.count("twist") == 1


def test_wants_politics_plain_twist_word_is_not_politics():
    # Pesan generate kategori animals yang kebetulan memuat kata "twist"
    # polos dari blok aturan (tanpa pemicu berkode/berkuotasi) tidak boleh
    # berubah menjadi fixture politik.
    messages = [
        Message(
            role="system",
            content=(
                "Twist rules: the twist scene corrects the popular claim. "
                "Beats flow: hook, setup, one or more main scenes, twist, "
                "payoff, cta."
            ),
        ),
        Message(
            role="user",
            content=(
                "Idea title: Kenapa cicak bisa menempel di dinding\n"
                "Category: animals"
            ),
        ),
    ]
    assert not _wants_politics(messages)


def metadata_messages(script_tail: str) -> list[Message]:
    return [
        Message(
            role="user",
            content=(
                "Topik: Kebijakan cicak di dinding\n"
                f"Naskah:\n{script_tail}\n"
                '{"title": "", "description": "", "hashtags": [], '
                '"fb_caption": ""}'
            ),
        )
    ]


async def test_fake_metadata_fixture_reuses_binary_closing_question():
    llm = FakeLLM()
    closing = "Kebijakan ini menolong warga atau malah memberatkan warga?"
    messages = metadata_messages(f"9. Kalimat penjelas terakhir\n10. {closing}")
    result = await llm.generate_text(
        TextRequest(messages=messages, response_schema=MetadataOutput)
    )
    output = MetadataOutput.model_validate(json.loads(result.text))
    assert closing in output.description


async def test_fake_metadata_fixture_fallback_is_binary_question():
    llm = FakeLLM()
    messages = metadata_messages(
        "10. Pernah mengalami hal serupa di rumah atau sekitarmu"
    )
    result = await llm.generate_text(
        TextRequest(messages=messages, response_schema=MetadataOutput)
    )
    output = MetadataOutput.model_validate(json.loads(result.text))
    assert " atau " in output.description
    assert "?" in output.description
    assert "paling mengejutkan" not in output.description
