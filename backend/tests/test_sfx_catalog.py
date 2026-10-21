from app.services import sfx_catalog


def test_catalog_files_exist():
    assert len(sfx_catalog.SFX_CATALOG) == 9
    for sfx_id in sfx_catalog.SFX_CATALOG:
        path = sfx_catalog.sfx_path(sfx_id)
        assert path.exists() and path.stat().st_size > 1000


def test_validity_and_gain():
    assert sfx_catalog.is_valid_sfx("ding")
    assert not sfx_catalog.is_valid_sfx("ledakan-besar")
    assert 0 < sfx_catalog.default_gain("boom") <= 1


def test_sanitize_filters_and_clamps():
    cues = [
        {"sfx": "boom", "word": "anjlok", "gain": 3.0},
        {"sfx": "tidak-ada", "word": "anjlok"},
        {"sfx": "ding", "word": "hantu"},
        {"sfx": "pop", "word": "pasar"},
        {"sfx": "cash", "word": "pasar"},
    ]
    cleaned = sfx_catalog.sanitize_sfx_cues(cues, "Indeks anjlok di pasar hari ini")
    assert [c["sfx"] for c in cleaned] == ["boom", "pop"]  # maks 2, urutan terjaga
    assert cleaned[0]["gain"] == 1.0  # gain terikat


def test_sanitize_drops_malformed_gain():
    cues = [
        {"sfx": "ding", "word": "anjlok", "gain": "keras"},
        {"sfx": "pop", "word": "anjlok", "gain": {"x": 1}},
        {"sfx": "boom", "word": "anjlok", "gain": float("nan")},
        {"sfx": "cash", "word": "anjlok", "gain": 0.4},
    ]
    cleaned = sfx_catalog.sanitize_sfx_cues(cues, "Harga anjlok hari ini")
    assert [c["sfx"] for c in cleaned] == ["cash"]
    assert cleaned[0]["gain"] == 0.4
