import json
import re
import typing

from pydantic import BaseModel

from app.providers.base import LLMCaps, Message, TextRequest, TextResult, Usage

_QUESTION_LEAD = re.compile(
    r"^(kenapa|mengapa|apa|bagaimana|kenalkah|tahukah kamu)\s+", flags=re.IGNORECASE
)


def _minimal_value(annotation) -> object:
    origin = typing.get_origin(annotation)
    if origin is list:
        return []
    if origin is dict:
        return {}
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _minimal_dict(annotation)
    return None


def _minimal_dict(schema: type[BaseModel]) -> dict:
    return {name: _minimal_value(field.annotation) for name, field in schema.model_fields.items()}


def _topic_core(messages) -> str:
    for message in messages:
        for line in message.content.splitlines():
            if line.strip().lower().startswith(("topik:", "judul project:")):
                topic = line.split(":", 1)[1].strip().rstrip(".")
                topic = _QUESTION_LEAD.sub("", topic)
                words = topic.split()
                return " ".join(words[:6]) or "topik ini"
    return "topik ini"


def _ideas_fixture(messages) -> dict:
    core = _topic_core(messages)
    cap = core[:1].upper() + core[1:]
    frames = [
        (f"Kenapa {core} bisa terjadi begitu saja?", "low", None),
        (f"Apa yang sebenarnya terjadi di balik {core}?", "low", None),
        (f"{cap}: fakta yang jarang dibahas orang", "low", None),
        (
            f"Mitos atau fakta soal {core}? Kita periksa",
            "check",
            f"Sebagian kepercayaan soal {core} belum diuji dengan data yang kuat.",
        ),
        (f"Apa jadinya kalau {core} berhenti terjadi?", "low", None),
        (
            f"Rahasia kecil di balik {core} yang mengejutkan",
            "check",
            f"Penjelasan populer soal {core} masih menyisakan bagian yang belum pasti.",
        ),
        (f"Kenapa tidak semua orang sadar soal {core} ini?", "low", None),
        (f"{cap} dan hal-hal aneh yang menyertainya", "low", None),
    ]
    ideas = []
    for i, (title, risk, note) in enumerate(frames, start=1):
        ideas.append(
            {
                "title": title,
                "angle": f"Penjelasan konkret nomor {i} tentang {core}, dari sebab sampai akibatnya",
                "hook": f"Berhenti scroll sebentar, {core} ternyata tidak sesederhana itu",
                "why_it_works": "Dekat dengan pengalaman penonton sehari-hari",
                "fact_risk": risk,
                "fact_note": note,
            }
        )
    return {"suggested_category": "animals", "ideas": ideas}


_SCRIPT_VOICEOVERS = [
    # (beat, voiceover, visual_type, mascot, keyword_text); hook diisi dinamis.
    ("hook", None, "character", True, None),
    ("setup", "Banyak orang melihatnya tetapi jarang ada yang memperhatikan", "closeup", True, "SERING LEWAT"),
    ("main", "Padahal ada penjelasan sederhana di balik kejadian ini", "character", True, "PENJELASAN"),
    ("main", "Penjelasan itu berkaitan dengan kebiasaan dan lingkungan sekitarnya", "environment", False, "KEBIASAAN"),
    ("main", "Saat kondisi berubah tubuh langsung menyesuaikan diri perlahan", "process", True, "MENYESUAIKAN DIRI"),
    ("main", "Penyesuaian ini membantu bertahan dari gangguan di sekitarnya", "diagram", True, "BERTAHAN"),
    ("main", "Tidak semua kejadian menunjukkan proses yang sama persis", "character", False, "TIDAK SELALU"),
    ("main", "Ada kalanya prosesnya gagal dan hasilnya berbeda jauh", "closeup", True, "BISA GAGAL"),
    ("payoff", "Jadi kejadian tadi bukan kebetulan tanpa sebab apa pun", "character", True, "BUKAN KEBETULAN"),
    ("cta", "Pernah mengalami hal serupa di rumah atau sekitarmu", "environment", True, None),
]

# Baris pengganti untuk fixture kategori politik (Fase 9+10): indeks 5 =
# beat twist (koreksi eksplisit berpenanda + kalimat adil, tanpa angka),
# indeks 6 dan 7 = tepat 2 beat impact sesudah main dan sebelum cta —
# pertama ke dapur/dompet, kedua ke tabungan/masa depan; indeks 9 =
# penutup berupa pertanyaan CTA biner.
_SCRIPT_POLITICS_OVERRIDES = {
    5: ("twist", "Ternyata klaim tadi keliru, biar adil catat juga sisi baiknya", "diagram", True, "TERNYATA KELIRU"),
    6: ("impact", "Akibatnya harga kebutuhan di dapur ikut naik perlahan", "environment", False, "HARGA NAIK"),
    7: ("impact", "Tabungan warga ikut tergerus dan masa depan makin berat", "diagram", True, "TABUNGAN"),
    9: ("cta", "Kebijakan ini menolong warga atau malah memberatkan warga?", "environment", True, None),
}


def _wants_politics(messages: list[Message]) -> bool:
    """Fixture politik bila prompt menyebut kategori politik, atau draf/issues
    yang diperbaiki sudah membawa beat impact / isu impact_chain (Fase 9),
    beat twist / isu twist_structure / isu binary_cta (Fase 10). Kata
    "twist" polos BUKAN pemicu: blok aturan twist muncul di prompt semua
    kategori, jadi hanya bentuk berkode/berkuotasi yang memicu."""
    joined = "\n".join(m.content for m in messages).lower()
    return (
        "politik" in joined
        or "impact_chain" in joined
        or '"impact"' in joined
        or "twist_structure" in joined
        or "binary_cta" in joined
        or '"twist"' in joined
    )


def _script_fixture(messages: list[Message]) -> dict:
    title = "Topik tanpa judul"
    for message in messages:
        for line in message.content.splitlines():
            if line.startswith("Idea title:"):
                title = line.removeprefix("Idea title:").strip() or title
    core = " ".join(_QUESTION_LEAD.sub("", title).rstrip(".").split()[:6]) or "topik ini"
    politics = _wants_politics(messages)
    rows = [
        _SCRIPT_POLITICS_OVERRIDES.get(i, row) if politics else row
        for i, row in enumerate(_SCRIPT_VOICEOVERS)
    ]
    scenes = []
    for i, (beat, template, visual_type, mascot, keyword) in enumerate(rows, start=1):
        if template is None:
            # Hook = parafrasa dekat judul (satu kalimat induk, Fase 9):
            # kata-kata inti judul itu sendiri, diawali huruf kapital.
            voiceover = core[:1].upper() + core[1:]
            keyword = core.split()[0].upper()[:18]
        else:
            voiceover = template
        scenes.append(
            {
                "beat": beat,
                "voiceover": voiceover,
                "subtitle": None,
                "visual_prompt": (
                    f"A simple scene about {core}, moment {i}"
                    if mascot
                    else f"[NO_MASCOT] A simple scene about {core}, moment {i}"
                ),
                "include_mascot": mascot,
                "visual_type": visual_type,
                "transition": "cut",
                "emphasis_words": [],
                "keyword_text": keyword,
            }
        )
    return {
        "schema_version": "script.v1",
        "title": title,
        "hook": scenes[0]["voiceover"],
        "scenes": scenes,
        "claims_to_verify": [
            f"Klaim utama tentang {core}",
            "Angka atau fakta pendukung yang disebut di dalam narasi",
        ],
    }


_BINARY_FALLBACK_QUESTION = "Kebijakan ini membantu warga atau malah memberatkan warga?"


def _binary_question(messages) -> str | None:
    """Pertanyaan biner penutup naskah dari prompt metadata (Fase 10):
    kalimat terakhir yang memuat " atau " dan "?", dengan kedua sisi
    "atau" masing-masing >= 2 kata dan tidak identik (pola cek
    binary_cta). Scene penutup ada di prompt sebagai script_text, jadi
    kandidat terakhir yang sah adalah pertanyaan penutupnya."""
    joined = "\n".join(m.content for m in messages)
    found = None
    for match in re.finditer(r"[^.!?\n]*\?", joined):
        sentence = match.group(0).strip().strip("\"'").strip()
        label, sep, rest = sentence.partition(": ")
        if sep and len(label.split()) <= 3:
            sentence = rest.strip()
        if not sentence.endswith("?"):
            continue
        atau = list(re.finditer(r"\batau\b", sentence, flags=re.IGNORECASE))
        if not atau:
            continue
        split = atau[-1]

        def _side(text: str) -> list[str]:
            return [
                t
                for t in (
                    token.strip(".,!?;:\"'()").lower()
                    for token in text.split()
                )
                if t
            ]

        left = _side(sentence[: split.start()])
        right = _side(sentence[split.end() :])
        if len(left) >= 2 and len(right) >= 2 and left != right:
            found = sentence
    return found


def _metadata_fixture(messages) -> dict:
    core = _topic_core(messages)
    cap = core[:1].upper() + core[1:]
    question = _binary_question(messages) or _BINARY_FALLBACK_QUESTION
    return {
        "title": f"{cap} — Penonton Wajib Tahu!",
        "description": (
            f"Video ini membahas {core} dengan bahasa sederhana. "
            f"{question} Tulis di komentar!"
        ),
        "hashtags": ["tikusberdasi", "shorts", "berita"],
        "fb_caption": f"{cap}! Simak sampai habis. #tikusberdasi #shorts",
    }


def _validation_fixture() -> dict:
    return {
        "status": "PASS",
        "score": 85,
        "summary": "Script rapi, hook jujur, dan alur mudah diikuti (mode kering).",
        "issues": [],
        "claims_to_verify": [],
    }


class FakeLLM:
    caps = LLMCaps(structured="json_object")

    async def generate_text(self, req: TextRequest, ctx=None) -> TextResult:
        joined = "\n".join(m.content for m in req.messages)
        if "(pattern ^(PASS" in joined:
            # Penanda kontrak ValidationOutput; JSON validator yang tertanam di
            # prompt revise/fix tidak memuat pola ini, jadi tidak salah deteksi.
            payload = _validation_fixture()
        elif "schema_version" in joined:
            payload = _script_fixture(req.messages)
        elif '"score"' in joined and '"summary"' in joined:
            payload = _validation_fixture()
        elif "fb_caption" in joined:
            payload = _metadata_fixture(req.messages)
        elif "suggested_category" in joined:
            # Mode json_object tidak mengirim schema; kontrak di prompt adalah penandanya.
            payload = _ideas_fixture(req.messages)
        elif req.response_schema is not None:
            payload = _minimal_dict(req.response_schema)
        else:
            payload = {"ok": True}
        text = json.dumps(payload)
        return TextResult(
            text=text,
            usage=Usage(input_tokens=0, output_tokens=len(text.split())),
            model="fake",
        )
