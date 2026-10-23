"""Fase 9 T5: prompt v2 — blok keyword_rules + impact_chain, revisi blok,
kategori politik, dan validate.script dengan 4 area benchmark Sukro."""

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


async def test_script_generate_v2_includes_keyword_and_impact_blocks(session):
    joined = await _render(session, "script.generate", SCRIPT_INPUTS)
    # blok keyword_rules: kata kunci 1-3 kata, contoh benchmark
    assert "keyword_text" in joined
    assert "DIJUAL" in joined and "PENSIUN" in joined
    assert "never a full sentence" in joined.lower()
    # blok impact_chain: rantai sebab-akibat sampai warga
    assert "sebab-akibat" in joined
    assert "impact" in joined
    # alur beat diperbarui: impact x2 untuk topik politik
    assert "impact x2" in joined


async def test_script_fix_and_revise_v2_include_new_blocks(session):
    fix_inputs = dict(
        SCRIPT_INPUTS, draft={"title": "x", "scenes": []}, issues=[]
    )
    joined_fix = await _render(session, "script.fix", fix_inputs)
    assert "DIJUAL" in joined_fix and "sebab-akibat" in joined_fix

    revise_inputs = dict(
        SCRIPT_INPUTS,
        draft={"title": "x", "scenes": []},
        validation={"status": "NEEDS_REVISION"},
        checks=[],
    )
    joined_revise = await _render(session, "script.revise", revise_inputs)
    assert "DIJUAL" in joined_revise and "sebab-akibat" in joined_revise


async def test_validate_script_active_is_v2_with_four_benchmark_areas(session):
    await sync_prompts(session)
    await session.commit()
    service = PromptService(session)
    version = await service._active_version("validate.script")
    # Fase 10 menaikkan validate.script ke v3, Fase 11 ke v4 (superset:
    # 4 area benchmark Fase 9 tetap ada, ditambah twist + CTA biner dan
    # kriteria keluwesan tuturan) — versi aktif kini 4.
    assert version.version == 4
    body = await service.active_body("validate.script")
    # (a) keyword coverage, (b) budget angka, (c) rantai impact, (d) judul-hook
    assert "keyword" in body.lower()
    assert "number budget" in body.lower()
    assert "sebab-akibat" in body
    assert "title" in body.lower() and "hook" in body.lower()
    assert "must not PASS" in body


async def test_visual_rules_no_longer_bans_text_outright(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("block.visual_rules")
    assert (
        "Never ask for text, letters, numbers, logos, or watermarks inside the image."
        not in body
    )
    assert "keyword_text" in body


async def test_safe_zone_keeps_top_clear_for_keyword_overlay(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("block.safe_zone")
    assert "top 22%" in body
    assert "bottom quarter" in body  # aturan lama tetap utuh


async def test_politics_category_requires_impact_chain(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("category.politics")
    assert "sebab-akibat" in body
    assert "dapur" in body and "dompet" in body
    # keamanan satir + fact-check strict tidak berubah
    assert "jangan pernah menyebut nama tokoh" in body
