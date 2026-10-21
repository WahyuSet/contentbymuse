from pydantic import BaseModel, Field


class IdeaItem(BaseModel):
    title: str = Field(
        min_length=20,
        max_length=90,
        description="Judul video, 20 sampai 90 karakter, berupa pertanyaan atau pernyataan penasaran",
    )
    angle: str = Field(description="Jawaban konkret yang akan dibahas video, tanpa nama mekanisme rasa penasaran")
    hook: str = Field(description="Satu kalimat pembuka yang menahan penonton, tidak membuka jawaban")
    why_it_works: str = Field(description="Kenapa ide ini menarik bagi penonton awam")
    fact_risk: str = Field(
        pattern="^(low|check)$",
        description="check bila jawaban bergantung pada mekanisme yang diperdebatkan atau premis yang belum mapan",
    )
    fact_note: str | None = Field(
        default=None, description="Wajib bila fact_risk=check: satu kalimat tentang apa yang belum pasti"
    )


class IdeasOutput(BaseModel):
    suggested_category: str | None = Field(
        default=None, description="Slug kategori yang paling cocok, dari daftar kategori yang tersedia"
    )
    ideas: list[IdeaItem] = Field(description="Tepat 8 ide")


class SceneDraft(BaseModel):
    beat: str = Field(
        pattern="^(hook|setup|main|payoff|cta|loop)$",
        description="Peran scene dalam alur: hook, setup, main, payoff, cta, loop",
    )
    voiceover: str = Field(description="Narasi lisan Bahasa Indonesia, 3 sampai 16 kata")
    subtitle: str | None = Field(default=None, description="Teks subtitle bila berbeda dari voiceover")
    visual_prompt: str = Field(description="Prompt gambar dalam Bahasa Inggris, satu adegan visual")
    include_mascot: bool = Field(default=True, description="True bila maskot stickman berkepala hijau tampil")
    visual_type: str = Field(
        pattern="^(character|object|process|environment|diagram|closeup)$",
        description="Jenis visual utama scene",
    )
    transition: str = Field(
        default="cut",
        pattern="^(cut|crossfade|punch_in)$",
        description="Transisi masuk ke scene ini",
    )
    emphasis_words: list[str] = Field(
        default_factory=list, description="Kata dari voiceover yang disorot di subtitle"
    )


class ScriptDraft(BaseModel):
    schema_version: str = Field(default="script.v1", description="Selalu script.v1")
    title: str = Field(description="Judul video")
    hook: str = Field(description="Sama persis dengan voiceover scene pertama")
    scenes: list[SceneDraft] = Field(description="8 sampai 14 scene berurutan")
    claims_to_verify: list[str] = Field(
        default_factory=list, description="Klaim fakta yang harus dicek pemilik sebelum menyetujui"
    )


class ValidationIssue(BaseModel):
    severity: str = Field(pattern="^(error|warning|suggestion)$")
    area: str = Field(description="content, script, scenes, voiceover, atau platform")
    scene_position: int | None = None
    message: str
    suggestion: str | None = None
    needs_change: bool = True


class ValidationOutput(BaseModel):
    status: str = Field(pattern="^(PASS|NEEDS_REVISION|FAIL)$")
    score: int = Field(ge=0, le=100)
    summary: str
    issues: list[ValidationIssue] = Field(default_factory=list)
    claims_to_verify: list[str] = Field(default_factory=list)


OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "IdeasOutput": IdeasOutput,
    "ScriptDraft": ScriptDraft,
    "ValidationOutput": ValidationOutput,
}
