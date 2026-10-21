import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Project, Scene, Script, ValidationResult
from app.domain.llm_outputs import SceneDraft, ScriptDraft, ValidationOutput
from app.domain.script_rules import apply_validation_rules, validate_script_draft
from app.services.settings import get_setting, set_setting


async def test_script_and_scene_persist(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    script = Script(project_id=project.id, version=1, title="Judul", hook="Hook")
    session.add(script)
    await session.flush()
    session.add(
        Scene(
            script_id=script.id,
            position=1,
            beat="hook",
            voiceover="Cicak memutus ekornya sendiri",
            visual_prompt="A gecko drops its tail",
            visual_type="character",
        )
    )
    project.active_script_id = script.id
    await session.commit()
    assert script.status == "draft"
    assert script.claims_to_verify == []


async def test_script_version_unique_per_project(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    session.add(Script(project_id=project.id, version=1, title="A", hook="h"))
    await session.commit()
    session.add(Script(project_id=project.id, version=1, title="B", hook="h"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_validation_result_and_settings(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    script = Script(project_id=project.id, version=1, title="A", hook="h")
    session.add(script)
    await session.flush()
    session.add(
        ValidationResult(script_id=script.id, attempt=1, status="PASS", score=90, job_id="01J")
    )
    await set_setting(session, "validation_provider_id", "01JPROV")
    await session.commit()
    assert await get_setting(session, "validation_provider_id") == "01JPROV"
    assert await get_setting(session, "tidak-ada", "bawaan") == "bawaan"


def scene(i: int, words: int = 7, **over) -> SceneDraft:
    base = {
        "beat": "hook" if i == 1 else "main",
        "voiceover": " ".join(["kata"] * words),
        "subtitle": None,
        "visual_prompt": f"Visual number {i}",
        "include_mascot": True,
        "visual_type": "character",
        "transition": "cut",
        "emphasis_words": [],
    }
    base.update(over)
    return SceneDraft(**base)


def draft(n=10, **kw) -> ScriptDraft:
    return ScriptDraft(
        title="Judul Script",
        hook="hook apa pun",
        scenes=[scene(i + 1, **kw) for i in range(n)],
        claims_to_verify=["klaim satu"],
    )


def test_validate_draft_scene_count_and_words():
    validate_script_draft(draft())
    with pytest.raises(ValueError, match="8 sampai 14"):
        validate_script_draft(draft(n=7))
    with pytest.raises(ValueError, match="kata"):
        validate_script_draft(draft(words=2))


def test_validate_draft_copies_hook_and_strips_no_mascot():
    made = draft()
    made.scenes[0].voiceover = "Cicak sengaja memutus ekornya sendiri"
    made.scenes[1].visual_prompt = "[NO_MASCOT] A tail on the floor"
    validated = validate_script_draft(made)
    assert validated.hook == "Cicak sengaja memutus ekornya sendiri"
    assert validated.scenes[1].visual_prompt == "A tail on the floor"
    assert validated.scenes[1].include_mascot is False


def test_validation_rules_downgrade_pass_with_error():
    output = ValidationOutput(
        status="PASS",
        score=90,
        summary="ok",
        issues=[
            {
                "severity": "error",
                "area": "script",
                "scene_position": 2,
                "message": "masalah",
                "suggestion": "perbaiki",
                "needs_change": True,
            }
        ],
        claims_to_verify=[],
    )
    assert apply_validation_rules(output).status == "NEEDS_REVISION"
