from app.services import sfx_catalog


def test_catalog_files_exist():
    # Katalog = whoosh transisi + SFX event kiriman pemilik (2026-10-23).
    assert set(sfx_catalog.SFX_CATALOG) == {"whoosh", "ding", "boom", "punch"}
    for sfx_id in sfx_catalog.SFX_CATALOG:
        path = sfx_catalog.sfx_path(sfx_id)
        assert path.exists() and path.stat().st_size > 1000


def test_validity_and_gain():
    assert sfx_catalog.is_valid_sfx("whoosh")
    assert sfx_catalog.is_valid_sfx("ding")
    assert sfx_catalog.is_valid_sfx("boom")
    assert sfx_catalog.is_valid_sfx("punch")
    assert not sfx_catalog.is_valid_sfx("pop")
    assert not sfx_catalog.is_valid_sfx("ledakan-besar")
    assert 0 < sfx_catalog.default_gain("boom") <= 1


def test_sanitize_filters_and_clamps():
    cues = [
        {"sfx": "whoosh", "word": "anjlok", "gain": 3.0},
        {"sfx": "tidak-ada", "word": "anjlok"},
        {"sfx": "whoosh", "word": "hantu"},
    ]
    cleaned = sfx_catalog.sanitize_sfx_cues(cues, "Indeks anjlok di pasar hari ini")
    # 'tidak-ada' tak dikenal; 'hantu' tak ada di narasi; gain terikat ke 1.0.
    assert [c["sfx"] for c in cleaned] == ["whoosh"]
    assert cleaned[0]["gain"] == 1.0


def test_sanitize_drops_malformed_gain():
    cues = [
        {"sfx": "whoosh", "word": "anjlok", "gain": "keras"},
        {"sfx": "whoosh", "word": "anjlok", "gain": {"x": 1}},
        {"sfx": "whoosh", "word": "anjlok", "gain": float("nan")},
        {"sfx": "whoosh", "word": "anjlok", "gain": 0.4},
    ]
    cleaned = sfx_catalog.sanitize_sfx_cues(cues, "Harga anjlok hari ini")
    assert [c["sfx"] for c in cleaned] == ["whoosh"]
    assert cleaned[0]["gain"] == 0.4
