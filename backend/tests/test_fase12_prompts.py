"""Fase 12 T3: blok mascot — peran pelaku bukan presenter, panggilan ekspresi
per beat dari set baku, skala figur terbesar, kehadiran diperketat; satu
baris komposisi maskot di visual_rules."""

from app.services.prompts import PromptService, sync_prompts


async def _body(session, key):
    await sync_prompts(session)
    await session.commit()
    return await PromptService(session).active_body(key)


async def test_mascot_block_role_is_perpetrator_not_presenter(session):
    body = await _body(session, "block.mascot")
    assert "PERPETRATOR" in body
    assert "never a presenter" in body
    # izin lama "two or three scenes mascot-free" hilang
    assert "two or three" not in body


async def test_mascot_block_expression_set_and_beat_guide(session):
    body = await _body(session, "block.mascot")
    for name in (
        "smug sly grin",
        "gleeful laugh",
        "shocked wide-eyed panic",
        "fake innocent wide smile",
        "angry defensive scowl",
    ):
        assert name in body
    # panduan beat: twist = panik ketahuan, penutup = polos palsu
    assert "twist" in body and "closing" in body


async def test_mascot_block_scale_and_presence(session):
    body = await _body(session, "block.mascot")
    assert "largest figure in the frame" in body
    assert "40%" in body
    assert "at most two scenes" in body
    assert "[NO_MASCOT]" in body  # mekanisme lama tetap utuh


async def test_visual_rules_mascot_is_largest_figure(session):
    body = await _body(session, "block.visual_rules")
    assert "largest figure in the frame" in body
    assert "keyword_text" in body  # aturan Fase 9 tidak berubah
