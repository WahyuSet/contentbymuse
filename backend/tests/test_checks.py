from app.domain.script_rules import extract_key_numbers, run_checks

CLEAN = [
    ("hook", "Kenapa cicak sengaja memutus ekornya sendiri", "character", True),
    ("setup", "Ekor itu terus bergerak sesudah lepas dari tubuh", "closeup", True),
    ("main", "Gerakan ekor mengalihkan perhatian musuh yang mengejar cicak", "character", False),
    ("main", "Cicak lalu kabur dan bersembunyi di celah sempit", "environment", True),
    ("main", "Beberapa minggu kemudian ekor baru tumbuh lagi perlahan", "process", True),
    ("main", "Ekor baru tidak punya tulang seperti ekor aslinya", "diagram", False),
    ("main", "Kemampuan ini membantu cicak selamat dari banyak predator", "character", True),
    ("main", "Jadi ekor putus bukan tanda cicak sedang sekarat", "closeup", True),
    ("payoff", "Justru itu cara cicak menipu musuh dan pulang selamat", "character", True),
    ("cta", "Pernah lihat ekor cicak bergerak sendiri di lantai", "environment", True),
]


def scenes(rows=None):
    rows = rows if rows is not None else CLEAN
    return [
        {
            "position": i + 1,
            "beat": beat,
            "voiceover": voiceover,
            "visual_prompt": f"Visual scene {i + 1}",
            "visual_type": visual_type,
            "include_mascot": mascot,
        }
        for i, (beat, voiceover, visual_type, mascot) in enumerate(rows)
    ]


def codes(issues):
    return {issue.code for issue in issues}


def test_clean_script_has_no_issues():
    assert run_checks(scenes()) == []


def test_scene_count_error():
    issues = run_checks(scenes(CLEAN[:7]))
    assert "scene_count" in codes(issues)
    assert next(i for i in issues if i.code == "scene_count").severity == "error"


def test_duration_range_error_mentions_word_delta():
    rows = [("main", "Satu dua tiga empat lima", "character", True)] * 10
    rows[0] = ("hook", rows[0][1], "character", True)
    issues = run_checks(scenes(rows))
    issue = next(i for i in issues if i.code == "duration_range")
    assert issue.severity == "error"
    assert "kata" in issue.message


def test_hook_length_error():
    rows = [CLEAN[0]] + CLEAN[1:]
    rows[0] = ("hook", "Kenapa cicak rumah sengaja memutus ekornya sendiri saat dikejar musuh besar", "character", True)
    issues = run_checks(scenes(rows))
    assert "hook_length" in codes(issues)


def test_scene_too_long_and_too_short():
    rows = list(CLEAN)
    rows[2] = ("main", "Satu dua tiga empat lima enam tujuh delapan sembilan sepuluh sebelas dua belas tiga belas", "character", False)
    rows[3] = ("main", "Kabur sekarang", "environment", True)
    found = codes(run_checks(scenes(rows)))
    assert "scene_too_long" in found
    assert "scene_too_short" in found


def test_visual_repeat_and_mascot_ratio():
    rows = [(b, v, "character", True) for b, v, _t, _m in CLEAN]
    found = codes(run_checks(scenes(rows)))
    assert "visual_repeat" in found
    assert "mascot_ratio" in found


def test_empty_field_and_duplicate():
    rows = list(CLEAN)
    rows[4] = ("main", "", "process", True)
    rows[5] = rows[1]
    found = codes(run_checks(scenes(rows)))
    assert "empty_field" in found
    assert "duplicate_voiceover" in found


def test_tts_risk_symbols_and_caps():
    rows = list(CLEAN)
    rows[2] = ("main", "Keberhasilan kabur mencapai 90% dari semua percobaan", "character", False)
    rows[3] = ("main", "KPK RI mencatat kasus serupa pada hewan lain", "environment", True)
    issues = [i for i in run_checks(scenes(rows)) if i.code == "tts_risk"]
    assert len(issues) == 2


def test_beat_order_and_loop_dangling():
    rows = list(CLEAN)
    rows[0] = ("setup", CLEAN[0][1], "character", True)
    rows[9] = ("loop", "Ekor cicak masih bergerak di lantai rumahmu.", "environment", True)
    found = codes(run_checks(scenes(rows)))
    assert "beat_order" in found
    assert "loop_dangling" in found


def test_written_register_and_repeated_opener():
    rows = list(CLEAN)
    rows[2] = ("main", "Ekor tersebut adalah bagian yang bisa tumbuh lagi", "character", False)
    rows[5] = ("main", "Gerakan kaki cicak menempel kuat di dinding", "diagram", False)
    rows[6] = ("main", "Gerakan ekornya membuat musuh bingung sesaat", "character", True)
    found = codes(run_checks(scenes(rows)))
    assert "written_register" in found
    assert "repeated_opener" in found


def test_numbered_points_only_for_top_list():
    rows = list(CLEAN)
    rows[1] = ("main", "Pertama, ekor cicak bergerak sendiri sesudah putus", "closeup", True)
    rows[2] = ("main", "Kedua, gerakan itu mengalihkan perhatian musuh", "character", False)
    rows[3] = ("main", "Ketiga, cicak kabur dan bersembunyi dengan aman", "environment", True)
    assert "numbered_points" not in codes(run_checks(scenes(rows), format_slug="top-list"))
    assert "numbered_points" in codes(run_checks(scenes(), format_slug="top-list"))
    assert "numbered_points" not in codes(run_checks(scenes()))


# --- Fase 9 T2: budget angka kunci ---


def test_extract_digit_numbers():
    found = extract_key_numbers("Denda 11 miliar dan 2,1 triliun di tahun 2027")
    assert found == {11, 2.1, 2027}


def test_extract_spelled_numbers():
    assert extract_key_numbers("Sebelas korporasi ditetapkan sebagai tersangka") == {11}
    assert extract_key_numbers("Dua belas orang ikut diperiksa penyidik") == {12}
    assert extract_key_numbers("Seratus warga antre sejak pagi hari") == {100}
    assert extract_key_numbers("Dua ratus lima puluh warga terdampak langsung") == {250}


def test_extract_spelled_compound_and_scale_as_one_number():
    found = extract_key_numbers("Anggaran tiga puluh satu triliun rupiah bocor")
    assert found == {31_000_000_000_000}
    assert extract_key_numbers("Sembilan ratus ribu warga kehilangan layanan") == {900_000}
    assert extract_key_numbers("Lima ribu orang menunggu kepastian") == {5_000}


def test_extract_numbers_dedupes_repeats():
    found = extract_key_numbers("Angka 11 muncul lagi, tetap 11 dan sebelas")
    assert found == {11}


def test_number_budget_passes_at_exactly_three_distinct():
    rows = list(CLEAN)
    rows[2] = ("main", "Denda 11 miliar dijatuhkan ke korporasi nakal", "character", False)
    rows[3] = ("main", "Sebanyak 132 warga ikut menandatangani petisi penolakan", "environment", True)
    rows[4] = ("main", "Aturan baru berlaku penuh mulai tahun 2027 mendatang", "process", True)
    assert "number_budget" not in codes(run_checks(scenes(rows)))


def test_number_budget_fails_at_four_distinct():
    rows = list(CLEAN)
    rows[2] = ("main", "Denda 11 miliar dijatuhkan ke korporasi nakal", "character", False)
    rows[3] = ("main", "Sebanyak 132 warga ikut menandatangani petisi penolakan", "environment", True)
    rows[4] = ("main", "Aturan baru berlaku penuh mulai tahun 2027 mendatang", "process", True)
    rows[5] = ("main", "Lima puluh warga lainnya masih menunggu kepastian hukum", "diagram", False)
    issues = [i for i in run_checks(scenes(rows)) if i.code == "number_budget"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].scene_position is None
    assert "4" in issues[0].message


# --- Fase 9 T3: beat impact politik + Jaccard judul-hook ---


def with_beats(beats):
    return [
        (beat, CLEAN[i][1], CLEAN[i][2], CLEAN[i][3])
        for i, beat in enumerate(beats)
    ]


POLITICS_OK_BEATS = [
    "hook", "setup", "main", "main", "main", "main",
    "impact", "impact", "payoff", "cta",
]


def test_impact_chain_required_for_politics():
    issues = [i for i in run_checks(scenes(), category_slug="politics") if i.code == "impact_chain"]
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_impact_chain_passes_with_two_placed_impacts():
    rows = with_beats(POLITICS_OK_BEATS)
    assert "impact_chain" not in codes(run_checks(scenes(rows), category_slug="politics"))


def test_impact_chain_single_impact_fails():
    beats = list(POLITICS_OK_BEATS)
    beats[7] = "payoff"
    assert "impact_chain" in codes(run_checks(scenes(with_beats(beats)), category_slug="politics"))


def test_impact_chain_wrong_zone_fails():
    beats = ["hook", "impact", "impact", "main", "main", "main", "main", "payoff", "payoff", "cta"]
    assert "impact_chain" in codes(run_checks(scenes(with_beats(beats)), category_slug="politics"))


def test_impact_chain_skipped_for_non_politics():
    assert "impact_chain" not in codes(run_checks(scenes(), category_slug="animals"))
    assert "impact_chain" not in codes(run_checks(scenes()))


def test_title_hook_match_passes():
    title = CLEAN[0][1]
    assert "title_hook_mismatch" not in codes(run_checks(scenes(), title=title))


def test_title_hook_unrelated_fails():
    issues = [
        i for i in run_checks(scenes(), title="Resep rendang terenak untuk keluarga besar")
        if i.code == "title_hook_mismatch"
    ]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].scene_position == 1


def test_title_hook_skipped_without_title():
    assert "title_hook_mismatch" not in codes(run_checks(scenes(), title=None))
    assert "title_hook_mismatch" not in codes(run_checks(scenes()))


def test_extract_key_numbers_task_cases():
    assert extract_key_numbers("11") == {11}
    assert extract_key_numbers("2,1") == {2.1}
    assert extract_key_numbers("sebelas") == {11}
    assert extract_key_numbers("dua belas") == {12}
    assert extract_key_numbers("tiga puluh satu") == {31}
    assert extract_key_numbers("seratus") == {100}
    assert extract_key_numbers("sembilan ratus") == {900}
    assert extract_key_numbers("tiga puluh satu triliun") == {31_000_000_000_000}
    assert extract_key_numbers("sembilan ratus ribu") == {900_000}
    assert extract_key_numbers("sebelas persen dan sebelas lagi") == {11}


def test_number_budget_four_distinct_spelled_is_one_error():
    rows = list(CLEAN)
    rows[1] = ("setup", "Denda sebelas persen membuat warga kaget sekali", "closeup", True)
    rows[2] = ("main", "Total kerugian dua belas triliun rupiah tercatat", "character", False)
    rows[3] = ("main", "Harga naik tiga puluh satu ribu per kilo", "environment", True)
    rows[4] = ("main", "Sembilan ratus warga antre sejak pagi hari", "process", True)
    issues = [i for i in run_checks(scenes(rows)) if i.code == "number_budget"]
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_number_budget_three_distinct_with_repeats_passes():
    rows = list(CLEAN)
    rows[1] = ("setup", "Denda sebelas persen membuat warga kaget sekali", "closeup", True)
    rows[2] = ("main", "Angka sebelas itu diulang lagi di sini", "character", False)
    rows[3] = ("main", "Total kerugian dua belas triliun rupiah tercatat", "environment", True)
    rows[4] = ("main", "Harga naik tiga puluh satu ribu per kilo", "process", True)
    assert "number_budget" not in codes(run_checks(scenes(rows)))


# --- Fase 10 T2: beat twist politik ---

TWIST_OK = [
    ("hook", "Klaim pejabat harga pangan turun warga lega", "character", True),
    ("setup", "Pedagang pasar tersenyum mendengar kabar baik itu", "environment", True),
    ("main", "Harga beras diumumkan lebih murah dari sebelumnya", "closeup", False),
    ("main", "Banyak keluarga berharap belanja dapur makin ringan", "character", True),
    ("twist", "Ternyata klaim itu keliru dan warga yang menanggung", "diagram", False),
    ("impact", "Harga mi dan telur tetap mahal di pasar", "environment", True),
    ("impact", "Uang belanja keluarga habis lebih cepat tiap pekan", "closeup", True),
    ("payoff", "Janji murah ternyata hanya cerita di panggung", "character", False),
    ("payoff", "Warga kecil kembali menahan lapar malam ini", "environment", True),
    ("cta", "Menurutmu kebijakan ini menolong siapa sebenarnya kawan", "character", True),
]


def test_twist_structure_required_for_politics():
    issues = [
        i for i in run_checks(scenes(with_beats(POLITICS_OK_BEATS)), category_slug="politics")
        if i.code == "twist_structure"
    ]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].scene_position is None


def test_twist_structure_passes_with_placed_marked_twist():
    found = codes(run_checks(scenes(TWIST_OK), category_slug="politics"))
    assert "twist_structure" not in found
    assert "impact_chain" not in found
    assert "number_budget" not in found


def test_twist_structure_two_twists_fail():
    rows = list(TWIST_OK)
    rows[8] = ("twist", TWIST_OK[8][1], TWIST_OK[8][2], TWIST_OK[8][3])
    issues = [
        i for i in run_checks(scenes(rows), category_slug="politics")
        if i.code == "twist_structure"
    ]
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_twist_structure_twist_before_main_fails():
    rows = list(TWIST_OK)
    rows[1], rows[4] = rows[4], rows[1]
    assert "twist_structure" in codes(run_checks(scenes(rows), category_slug="politics"))


def test_twist_structure_twist_after_first_impact_fails():
    rows = list(TWIST_OK)
    rows[4], rows[5] = rows[5], rows[4]
    assert "twist_structure" in codes(run_checks(scenes(rows), category_slug="politics"))


def test_twist_structure_twist_without_marker_fails():
    rows = list(TWIST_OK)
    rows[4] = (
        "twist",
        "Klaim pejabat rupanya keliru dan warga yang menanggung",
        TWIST_OK[4][2],
        TWIST_OK[4][3],
    )
    assert "twist_structure" in codes(run_checks(scenes(rows), category_slug="politics"))


def test_twist_structure_skipped_for_non_politics():
    assert "twist_structure" not in codes(run_checks(scenes(), category_slug="animals"))
    assert "twist_structure" not in codes(run_checks(scenes()))


def test_twist_structure_other_markers_pass():
    for voiceover in (
        "Padahal klaim itu keliru dan warga yang menanggung",
        "Faktanya klaim itu keliru dan warga yang menanggung",
    ):
        rows = list(TWIST_OK)
        rows[4] = ("twist", voiceover, TWIST_OK[4][2], TWIST_OK[4][3])
        assert "twist_structure" not in codes(
            run_checks(scenes(rows), category_slug="politics")
        )
