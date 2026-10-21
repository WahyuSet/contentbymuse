from app.domain.llm_outputs import IdeasOutput
from app.services.prompts import PromptService, output_contract, parse_frontmatter, sync_prompts


def test_parse_frontmatter():
    meta, body = parse_frontmatter("---\nname: Hewan\nversion: 1\n---\nisi teks")
    assert meta["name"] == "Hewan" and body == "isi teks"


def test_output_contract_lists_fields_and_limits():
    contract = output_contract(IdeasOutput)
    assert "ideas" in contract and "title" in contract


async def test_sync_creates_templates_categories_formats(session):
    summary = await sync_prompts(session)
    await session.commit()
    assert summary["categories"] == 5 and summary["formats"] == 3
    again = await sync_prompts(session)
    assert again["versions"] == 0


async def test_sync_survives_inplace_file_edit(session, tmp_path):
    root = tmp_path / "prompts"
    (root / "categories").mkdir(parents=True)
    target = root / "categories" / "animals.md"
    target.write_text(
        "---\nname: Hewan\ndescription: awal\nfact_check: normal\nversion: 1\n---\nAturan versi satu.",
        encoding="utf-8",
    )
    await sync_prompts(session, root)
    await session.commit()
    target.write_text(
        "---\nname: Hewan\ndescription: berubah\nfact_check: normal\nversion: 1\n---\nAturan versi dua.",
        encoding="utf-8",
    )
    summary = await sync_prompts(session, root)
    await session.commit()
    assert summary["versions"] == 1
    body = await PromptService(session).active_body("category.animals")
    assert body == "Aturan versi dua."


async def test_render_ideas_prompt(session):
    await sync_prompts(session)
    await session.commit()
    service = PromptService(session)
    rendered = await service.render(
        "ideas.from_topic",
        {"topic": "cicak", "language": "id-ID", "category": None, "format": None},
    )
    assert rendered.output_model is IdeasOutput
    assert rendered.version_id
    joined = "\n".join(m.content for m in rendered.messages)
    assert "cicak" in joined and "Topik:" in joined
    assert rendered.messages[0].role == "system"
