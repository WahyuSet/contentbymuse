from app.jobs.thumbnail import _short_title


def test_short_title_strips_question_opener():
    assert _short_title("Kenapa cicak bisa menempel di dinding") == (
        "CICAK BISA MENEMPEL DI DINDING"
    )


def test_short_title_trims_weak_tail():
    assert _short_title("Berita tentang korporasi yang") == (
        "BERITA TENTANG KORPORASI"
    )


def test_short_title_plain_hook_unchanged():
    assert _short_title("Polri menetapkan 11 korporasi tersangka") == (
        "POLRI MENETAPKAN 11 KORPORASI TERSANGKA"
    )
