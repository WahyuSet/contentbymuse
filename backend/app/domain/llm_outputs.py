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


OUTPUT_MODELS: dict[str, type[BaseModel]] = {"IdeasOutput": IdeasOutput}
