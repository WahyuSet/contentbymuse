from app.domain.llm_outputs import ScriptDraft, ValidationOutput

_NO_MASCOT_TAG = "[NO_MASCOT]"


def count_words(text: str) -> int:
    return len(text.split())


def estimate_scene_s(voiceover: str, wps: float) -> float:
    return count_words(voiceover) / wps + 0.15


def validate_script_draft(draft: ScriptDraft) -> ScriptDraft:
    """Aturan bisnis ScriptDraft (Spec §3.2). Melempar ValueError berpesan spesifik."""
    n = len(draft.scenes)
    if not 8 <= n <= 14:
        raise ValueError(f"Jumlah scene wajib 8 sampai 14, diterima {n}.")
    for position, scene in enumerate(draft.scenes, start=1):
        words = count_words(scene.voiceover)
        if not 3 <= words <= 16:
            raise ValueError(
                f"Scene {position}: voiceover wajib 3 sampai 16 kata, sekarang {words} kata."
            )
        prompt = scene.visual_prompt.lstrip()
        if prompt.upper().startswith(_NO_MASCOT_TAG):
            scene.visual_prompt = prompt[len(_NO_MASCOT_TAG) :].lstrip()
            scene.include_mascot = False
    if draft.scenes:
        # Hook selalu narasi scene 1 (§3.2); disalin kode, bukan dipercaya dari LLM.
        draft.hook = draft.scenes[0].voiceover
    return draft


def apply_validation_rules(output: ValidationOutput) -> ValidationOutput:
    """Aturan bisnis ValidationOutput (Spec §3.3): PASS tidak boleh membawa error."""
    if output.status == "PASS" and any(
        issue.severity == "error" for issue in output.issues
    ):
        output.status = "NEEDS_REVISION"
    return output


import re
from dataclasses import dataclass


@dataclass
class CheckIssue:
    code: str
    severity: str
    scene_position: int | None
    message: str


_WRITTEN_WORDS = {"adalah", "bahwa", "merupakan", "tersebut", "tak", "yaitu", "dimana"}
_TTS_SYMBOLS = ("%", "&", "/")
_ROMAN_RE = re.compile(r"\b[IVXLCDM]{2,}\b")


def _field(scene, name, default=None):
    if isinstance(scene, dict):
        return scene.get(name, default)
    return getattr(scene, name, default)


def _token_set(text: str) -> set[str]:
    return {t.strip(".,!?").lower() for t in text.split() if t.strip(".,!?")}


# --- Ekstraktor angka kunci (Fase 9): digit + ejaan Indonesia ---

_DIGIT_RE = re.compile(r"\d+(?:,\d+)?")
_WORD_TOKEN_RE = re.compile(r"[a-z]+")
_ID_UNITS = {
    "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9,
}
_ID_SCALES = {
    "ribu": 1_000, "juta": 1_000_000,
    "miliar": 1_000_000_000, "triliun": 1_000_000_000_000,
}


def _parse_below_hundred(tokens: list[str], i: int):
    """Parse frasa angka <100 mulai di tokens[i]; kembalikan (nilai, indeks lanjut) atau None."""
    if i >= len(tokens):
        return None
    tok = tokens[i]
    if tok == "sepuluh":
        return (10, i + 1)
    if tok == "sebelas":
        return (11, i + 1)
    if tok in _ID_UNITS:
        unit = _ID_UNITS[tok]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt == "belas":
            return (10 + unit, i + 2)
        if nxt == "puluh":
            value, j = unit * 10, i + 2
            if j < len(tokens) and tokens[j] in _ID_UNITS:
                value += _ID_UNITS[tokens[j]]
                j += 1
            return (value, j)
        return (unit, i + 1)
    return None


def _parse_below_thousand(tokens: list[str], i: int):
    """Seperti _parse_below_hundred, plus bentuk ratus (seratus / <unit> ratus)."""
    if i < len(tokens) and tokens[i] == "seratus":
        rest = _parse_below_hundred(tokens, i + 1)
        return (100 + rest[0], rest[1]) if rest else (100, i + 1)
    if i + 1 < len(tokens) and tokens[i] in _ID_UNITS and tokens[i + 1] == "ratus":
        base = _ID_UNITS[tokens[i]] * 100
        rest = _parse_below_hundred(tokens, i + 2)
        return (base + rest[0], rest[1]) if rest else (base, i + 2)
    return _parse_below_hundred(tokens, i)


def _parse_number_at(tokens: list[str], i: int):
    """Parse SATU frasa angka di tokens[i], kecocokan terpanjang dulu.

    Kata skala (ribu/juta/miliar/triliun) yang mengikuti ikut jadi pengali,
    jadi "tiga puluh satu triliun" adalah satu angka 31 triliun, bukan dua.
    """
    if tokens[i] == "seribu":
        value, j = 1_000, i + 1
    else:
        parsed = _parse_below_thousand(tokens, i)
        if parsed is None:
            return None
        value, j = parsed
    if j < len(tokens) and tokens[j] in _ID_SCALES:
        value *= _ID_SCALES[tokens[j]]
        j += 1
    return (value, j)


def extract_key_numbers(text: str) -> set:
    """Himpunan angka kunci dalam teks VO: bentuk digit ("11", "2,1", "2027")
    dan ejaan Indonesia ("sebelas", "tiga puluh satu triliun", "sembilan ratus ribu").
    Nilai dinormalisasi (koma desimal -> float; ejaan termasuk skala -> int)."""
    found: set = set()
    for match in _DIGIT_RE.finditer(text or ""):
        raw = match.group(0)
        found.add(float(raw.replace(",", ".")) if "," in raw else int(raw))
    tokens = _WORD_TOKEN_RE.findall((text or "").lower())
    i = 0
    while i < len(tokens):
        parsed = _parse_number_at(tokens, i)
        if parsed is None:
            i += 1
        else:
            value, i = parsed
            found.add(value)
    return found


def _format_number(value) -> str:
    return str(value).replace(".", ",") if isinstance(value, float) else str(value)


def _tts_risk_detail(voiceover: str) -> str | None:
    for symbol in _TTS_SYMBOLS:
        if symbol in voiceover:
            return f"simbol {symbol}"
    if "http" in voiceover or "www." in voiceover:
        return "tautan"
    if _ROMAN_RE.search(voiceover):
        return "angka romawi"
    for token in voiceover.split():
        cleaned = token.strip(".,!?")
        if len(cleaned) >= 3 and cleaned.isalpha() and cleaned.isupper():
            return f"singkatan kapital {cleaned}"
    return None


def run_checks(
    scenes,
    *,
    wps: float = 2.3,
    target_min_s: int = 30,
    target_max_s: int = 40,
    format_slug: str | None = None,
) -> list[CheckIssue]:
    """Cek otomatis script (Spec §4.3). Murni: tidak menyentuh database."""
    scenes = list(scenes)
    issues: list[CheckIssue] = []
    n = len(scenes)

    def position_of(index: int, scene) -> int:
        return _field(scene, "position", index + 1)

    voiceovers = [(_field(s, "voiceover", "") or "") for s in scenes]
    word_counts = [count_words(v) for v in voiceovers]
    ests = [estimate_scene_s(v, wps) for v in voiceovers]
    total_words = sum(word_counts)
    total_est = sum(ests)

    if not 8 <= n <= 14:
        issues.append(CheckIssue(
            "scene_count", "error", None,
            f"Jumlah scene {n}, wajib 8 sampai 14 scene.",
        ))
    if n and (total_est < target_min_s or total_est > target_max_s):
        if total_est < target_min_s:
            delta = round((target_min_s - total_est) * wps)
            arah = f"perlu ditambah sekitar {delta} kata"
        else:
            delta = round((total_est - target_max_s) * wps)
            arah = f"perlu dipangkas sekitar {delta} kata"
        issues.append(CheckIssue(
            "duration_range", "error", None,
            f"Estimasi durasi total {total_est:.0f} detik dari {total_words} kata, "
            f"di luar target {target_min_s}-{target_max_s} detik; {arah}.",
        ))
    if n and ests[0] > 3.5:
        max_hook_words = int((3.5 - 0.15) * wps)
        issues.append(CheckIssue(
            "hook_length", "error", position_of(0, scenes[0]),
            f"Hook {word_counts[0]} kata, estimasi {ests[0]:.1f} detik; batas hook 3,5 detik "
            f"(sekitar {max_hook_words} kata).",
        ))

    for index, scene in enumerate(scenes):
        pos = position_of(index, scene)
        voiceover = voiceovers[index]
        visual = _field(scene, "visual_prompt", "") or ""
        words = word_counts[index]
        if not voiceover.strip():
            issues.append(CheckIssue(
                "empty_field", "error", pos, f"Scene {pos}: voiceover kosong."))
        if not visual.strip():
            issues.append(CheckIssue(
                "empty_field", "error", pos, f"Scene {pos}: visual_prompt kosong."))
        if voiceover.strip():
            if words > 12 or ests[index] > 5:
                issues.append(CheckIssue(
                    "scene_too_long", "warning", pos,
                    f"Scene {pos}: {words} kata, estimasi {ests[index]:.1f} detik; "
                    "rawan terpotong, pertimbangkan memecahnya."))
            if words < 3:
                issues.append(CheckIssue(
                    "scene_too_short", "warning", pos,
                    f"Scene {pos}: hanya {words} kata; penonton bisa kehilangan konteks."))
            detail = _tts_risk_detail(voiceover)
            if detail:
                issues.append(CheckIssue(
                    "tts_risk", "warning", pos,
                    f"Scene {pos}: {detail} berisiko dibaca aneh oleh TTS."))
            written = sorted(_token_set(voiceover) & _WRITTEN_WORDS)
            if written:
                issues.append(CheckIssue(
                    "written_register", "warning", pos,
                    f"Scene {pos}: kata ragam tulis ({', '.join(written)}) terdengar kaku diucapkan."))

    run_type = None
    run_len = 0
    for index, scene in enumerate(scenes):
        visual_type = _field(scene, "visual_type", "")
        run_len = run_len + 1 if visual_type == run_type else 1
        run_type = visual_type
        if run_len == 3:
            issues.append(CheckIssue(
                "visual_repeat", "warning", position_of(index, scene),
                f"Visual jenis {visual_type} muncul lebih dari dua scene berurutan; "
                "variasikan jenis visualnya."))

    if n:
        if all(_field(s, "include_mascot", True) for s in scenes):
            issues.append(CheckIssue(
                "mascot_ratio", "warning", None,
                "Maskot tampil di semua scene; sisakan scene tanpa maskot untuk variasi."))
        if not _field(scenes[0], "include_mascot", True):
            issues.append(CheckIssue(
                "mascot_ratio", "warning", position_of(0, scenes[0]),
                "Scene hook tanpa maskot; maskot adalah identitas channel."))

    token_sets = [_token_set(v) for v in voiceovers]
    for i in range(n):
        if not token_sets[i]:
            continue
        for j in range(i + 1, n):
            if not token_sets[j]:
                continue
            inter = len(token_sets[i] & token_sets[j])
            union = len(token_sets[i] | token_sets[j])
            if union and inter / union >= 0.9:
                issues.append(CheckIssue(
                    "duplicate_voiceover", "error", position_of(j, scenes[j]),
                    f"Scene {position_of(j, scenes[j])}: voiceover sama atau sangat mirip "
                    f"dengan scene {position_of(i, scenes[i])}."))

    if n:
        if _field(scenes[0], "beat", "") != "hook":
            issues.append(CheckIssue(
                "beat_order", "warning", position_of(0, scenes[0]),
                "Scene pertama bukan hook; video pendek wajib membuka dengan hook."))
        last = scenes[-1]
        last_beat = _field(last, "beat", "")
        if last_beat not in ("cta", "loop"):
            issues.append(CheckIssue(
                "beat_order", "warning", position_of(n - 1, last),
                "Scene terakhir bukan cta atau loop; video terasa terpotong."))
        if last_beat == "loop" and voiceovers[-1].rstrip().endswith((".", "!", "?")):
            issues.append(CheckIssue(
                "loop_dangling", "warning", position_of(n - 1, last),
                "Scene loop berakhir dengan tanda baca penutup; putaran ulang terasa menggantung."))

    openers = [v.split()[0].strip(".,!?").lower() if v.split() else "" for v in voiceovers]
    for index in range(1, n):
        if openers[index] and openers[index] == openers[index - 1]:
            issues.append(CheckIssue(
                "repeated_opener", "warning", position_of(index, scenes[index]),
                f"Scene {position_of(index, scenes[index])} membuka dengan kata yang sama "
                f"seperti scene sebelumnya ({openers[index]})."))
    jadi_positions = [i for i, opener in enumerate(openers) if opener == "jadi"]
    for index in jadi_positions[1:]:
        issues.append(CheckIssue(
            "repeated_opener", "warning", position_of(index, scenes[index]),
            "Kata 'jadi' membuka lebih dari satu scene; pembuka terasa monoton."))

    key_numbers: set = set()
    for voiceover in voiceovers:
        key_numbers |= extract_key_numbers(voiceover)
    if len(key_numbers) > 3:
        listed = ", ".join(_format_number(v) for v in sorted(key_numbers))
        issues.append(CheckIssue(
            "number_budget", "error", None,
            f"Angka kunci berbeda ada {len(key_numbers)} ({listed}), melebihi budget "
            "maksimal 3 angka kunci per video; ulangi angka yang sama atau potong angka lain.",
        ))

    if format_slug == "top-list":
        markers = ["pertama", "kedua", "ketiga"]
        found_at: list[int] = []
        cursor = 0
        lowered = [v.lower() for v in voiceovers]
        for marker in markers:
            hit = next(
                (k for k in range(cursor, n) if lowered[k].startswith(marker + ",")),
                None,
            )
            if hit is None:
                break
            found_at.append(hit)
            cursor = hit + 1
        if len(found_at) < 3:
            issues.append(CheckIssue(
                "numbered_points", "warning", None,
                "Format daftar bernomor tanpa awalan Pertama, Kedua, Ketiga yang berurutan; "
                "penomoran membantu penonton mengikuti."))

    return issues
