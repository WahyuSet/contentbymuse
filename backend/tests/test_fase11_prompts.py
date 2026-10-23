"""Fase 11 T3: prompt pacing + spoken_indonesian — durasi satu-satunya pagar
< 45 detik (tanpa lantai), kalimat utuh anti-fragmen, dan jangkar bahasa
untuk TTS (padanan Indonesia di voiceover, istilah Inggris di tengah kalimat).
"""

from app.services.prompts import PromptService, sync_prompts

SCRIPT_INPUTS = {
    "idea": {"title": "Cicak memutus ekor", "angle": "a", "hook": "h"},
    "category": None,
    "format": None,
    "language": "id-ID",
    "target_min_s": 0,
    "target_max_s": 45,
}


async def _render(session, task, inputs):
    await sync_prompts(session)
    await session.commit()
    rendered = await PromptService(session).render(task, inputs)
    return "\n".join(m.content for m in rendered.messages)


async def test_pacing_block_only_upper_bound_45_no_minimum(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("block.pacing")
    # batas atas 45 detik disebut (angka eksplisit dan/atau variabel template)
    assert "45" in body or "below" in body.lower()
    assert "{{ target_max_s }}" in body
    # klaim lama rentang 70-90 kata sudah hilang
    assert "70 to 90" not in body
    # maksimum kata kira-kira 100 untuk batas 45 detik
    assert "100" in body
    # tidak ada lantai: video pendek sah
    assert "no minimum" in body.lower()


async def test_spoken_indonesian_block_complete_sentences_and_anchor(session):
    await sync_prompts(session)
    await session.commit()
    body = await PromptService(session).active_body("block.spoken_indonesian")
    # contoh buruk verbatim dari video test data center (tiga fragmen)
    assert "pajak masuk, data pulang kampung" in body
    assert "PLN pelanggan raksasa, pajak masuk, data pulang kampung" in body
    assert "fragmen" in body
    # jangkar bahasa: padanan Indonesia yang hidup untuk voiceover
    assert "pusat data" in body
    # tes baca-keras: headline / judul berita
    assert "headline" in body or "judul berita" in body
    # larangan ragam tulis lama tetap ada
    assert "adalah" in body


async def test_script_generate_includes_fase11_blocks(session):
    joined = await _render(session, "script.generate", SCRIPT_INPUTS)
    # penanda unik blok pacing baru
    assert "100" in joined
    assert "no minimum" in joined.lower()
    assert "70 to 90" not in joined
    # penanda unik blok spoken_indonesian baru
    assert "pajak masuk, data pulang kampung" in joined
    assert "pusat data" in joined
    assert "fragmen" in joined


async def test_validate_script_active_is_v4_with_spoken_fluency(session):
    await sync_prompts(session)
    await session.commit()
    service = PromptService(session)
    version = await service._active_version("validate.script")
    assert version.version == 4
    body = await service.active_body("validate.script")
    # (g) Spoken fluency (keluwesan tuturan)
    assert "fluency" in body.lower() or "keluwesan" in body.lower()
    # contoh buruk verbatim dari video test data center (tiga fragmen)
    assert "pajak masuk, data pulang kampung" in body
    assert "PLN pelanggan raksasa, pajak masuk, data pulang kampung" in body


async def test_script_fix_and_revise_include_fase11_blocks(session):
    fix_inputs = dict(
        SCRIPT_INPUTS, draft={"title": "x", "scenes": []}, issues=[]
    )
    joined_fix = await _render(session, "script.fix", fix_inputs)
    assert "pusat data" in joined_fix
    assert "pajak masuk, data pulang kampung" in joined_fix
    assert "70 to 90" not in joined_fix

    revise_inputs = dict(
        SCRIPT_INPUTS,
        draft={"title": "x", "scenes": []},
        validation={"status": "NEEDS_REVISION"},
        checks=[],
    )
    joined_revise = await _render(session, "script.revise", revise_inputs)
    assert "pusat data" in joined_revise
    assert "pajak masuk, data pulang kampung" in joined_revise
    assert "70 to 90" not in joined_revise
