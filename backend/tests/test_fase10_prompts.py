"""Fase 10 T4-T5: prompt v3 — blok twist_rules + cta_rules, revisi hook_rules,
kategori politik dengan kewajiban twist + CTA biner, validate.script v3
dengan area Twist quality + Binary CTA, dan metadata.generate v2."""

from app.services.prompts import PromptService, sync_prompts

SCRIPT_INPUTS = {
    "idea": {"title": "Cicak memutus ekor", "angle": "a", "hook": "h"},
    "category": None,
    "format": None,
    "language": "id-ID",
    "target_min_s": 30,
    "target_max_s": 40,
}


async def _render(session, task, inputs):
    await sync_prompts(session)
    await session.commit()
    rendered = await PromptService(session).render(task, inputs)
    return "\n".join(m.content for m in rendered.messages)


async def test_twist_rules_block_content(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("block.twist_rules")
    assert "twist" in body
    assert "popular claim" in body
    assert "claims_to_verify" in body
    # salah satu penanda koreksi eksplisit harus disebut
    assert "ternyata" in body


async def test_cta_rules_block_content(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("block.cta_rules")
    assert "binary" in body.lower()
    assert "atau" in body
    assert "ganti kemasan" in body


async def test_script_generate_v3_includes_twist_and_cta_blocks(session):
    joined = await _render(session, "script.generate", SCRIPT_INPUTS)
    # blok twist_rules ter-render
    assert "popular claim" in joined
    assert "ternyata" in joined
    assert "claims_to_verify" in joined
    # blok cta_rules ter-render
    assert "binary" in joined.lower()
    assert "ganti kemasan" in joined
    # hook_rules hasil revisi menyebut twist
    assert "twist" in joined
    # alur beat diperbarui: twist untuk topik politik
    assert "twist (political topics only)" in joined
    # isi Fase 9 tetap ada
    assert "impact x2" in joined
    assert "keyword_text" in joined


async def test_script_fix_and_revise_v3_include_new_blocks(session):
    fix_inputs = dict(
        SCRIPT_INPUTS, draft={"title": "x", "scenes": []}, issues=[]
    )
    joined_fix = await _render(session, "script.fix", fix_inputs)
    assert "popular claim" in joined_fix and "ternyata" in joined_fix
    assert "binary" in joined_fix.lower() and "ganti kemasan" in joined_fix

    revise_inputs = dict(
        SCRIPT_INPUTS,
        draft={"title": "x", "scenes": []},
        validation={"status": "NEEDS_REVISION"},
        checks=[],
    )
    joined_revise = await _render(session, "script.revise", revise_inputs)
    assert "popular claim" in joined_revise and "ternyata" in joined_revise
    assert "binary" in joined_revise.lower() and "ganti kemasan" in joined_revise


async def test_validate_script_active_is_v3_with_twist_and_binary_areas(session):
    await sync_prompts(session)
    await session.commit()
    service = PromptService(session)
    version = await service._active_version("validate.script")
    assert version.version == 3
    body = await service.active_body("validate.script")
    # (e) Twist quality, (f) Binary CTA
    assert "twist" in body.lower()
    assert "binary" in body.lower()
    assert "must not PASS" in body
    # area Fase 9 tetap ada
    assert "number budget" in body.lower()
    assert "sebab-akibat" in body


async def test_metadata_generate_v2_requires_same_binary_question(session):
    await sync_prompts(session)
    await session.commit()
    service = PromptService(session)
    version = await service._active_version("metadata.generate")
    assert version.version == 2
    body = await service.active_body("metadata.generate")
    assert "binary" in body.lower() or "biner" in body.lower()
    assert "atau" in body


async def test_politics_category_requires_twist_and_binary_cta(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("category.politics")
    assert "twist" in body.lower()
    assert "ternyata" in body
    assert "biner" in body.lower()
    assert "atau" in body
    assert "claims_to_verify" in body
    # keamanan satir + rantai dampak Fase 9 tidak berubah
    assert "sebab-akibat" in body
    assert "jangan pernah menyebut nama tokoh" in body
