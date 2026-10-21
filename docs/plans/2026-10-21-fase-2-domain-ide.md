# Fase 2 — Domain, Prompt, dan Ide: Rencana Implementasi

> **Untuk agen pelaksana:** Wajib memakai sub-skill: gunakan superpowers:subagent-driven-development (disarankan) atau superpowers:executing-plans untuk menjalankan rencana ini per task. Langkah memakai kotak centang (`- [ ]`) untuk pelacakan.

**Tujuan:** Project bisa dibuat dari UI, kategori/format/prompt tersinkron dari file, dan satu topik menghasilkan tepat 8 ide yang bisa dipilih (Gerbang A) — lewat `PromptService` → `StructuredLLM` → adapter LLM (OpenAI-compatible atau `fake` untuk dry-run).

**Arsitektur:** Model domain baru (category, format, project, content_idea, provider, prompt_template, prompt_version) + migrasi 0002. File prompt di `backend/app/prompts/` adalah sumber kebenaran; saat startup isinya disinkronkan ke DB (template + versi + kategori + format). `StructuredLLM` membungkus adapter LLM mana pun: render prompt, panggil, bersihkan dan parse JSON, validasi Pydantic + aturan bisnis, satu retry dengan pesan error, lalu pindah provider berikutnya. Job `ideas` menulis satu batch 8 ide; memilih ide memanggil `reconcile`.

**Stack teknologi:** FastAPI, SQLAlchemy async, Alembic, Jinja2 (sudah ada), PyYAML (baru, untuk frontmatter), httpx + respx (sudah ada), React + TanStack Query.

## Konteks dari Spec (mengikat)

- Baris Fase 2 di Spec §14: "`PromptService`, `StructuredLLM`, adapter LLM, Kategori dan Format, seed provider, UI buat project + pilih ide. Selesai bila: Topik sungguhan menghasilkan 8 ide di UI."
- §2.1: `category`/`format` dibaca dari file `prompts/categories/*.md` dan `prompts/formats/*.md`, disinkronkan ke tabel saat startup; kolom `id, slug (unik), name, description, fact_check (hanya category: normal/strict), prompt_template_id (fk), enabled`.
- §2.1 `project`: kolom Fase 2 = `id, title, topic (null), category_id (fk null), category_source (user/suggested/null), format_id (fk null), language (default id-ID), target_min_s/target_max_s (default 30/40), selected_idea_id (fk null), settings (JSON), created_at, updated_at`. Constraint: `topic` ATAU `category_id` wajib terisi. Kolom `active_script_id`, `visual_style_id`, `voice_*`, `image_provider_id`, `video_provider_id` datang di fase pemakainya (catatan §2.1) — JANGAN dibuat di fase ini.
- §2.1 `content_idea`: `id, project_id, batch (int), position (1..8), title, angle, hook, why_it_works, suggested_category_slug, fact_risk (low/check), fact_note (null kecuali check), job_id, created_at`. `job_id` adalah kunci idempotensi: retry memakai batch yang ditulis job itu, bukan batch kedua.
- §2.3 `provider`: `id, name, capability, adapter, base_url (null), api_key_encrypted (bytes null, Fernet), default_model (null), quirks (JSON), enabled, priority, created_at, updated_at`. `prompt_template`: `id, key, kind (task/block/category/format), active_version_id`. `prompt_version`: `id, template_id, version, source (builtin/user), content, frontmatter (JSON), content_hash, created_at`, tidak pernah diubah.
- §3.1 `IdeasOutput` (`ideas.v1`): tepat 8 ide; `title` 20–90 karakter; kemiripan antar-judul (rasio token) < 0,8; `suggested_category` slug yang ada, bila tidak → `null`. `fact_risk` wajib (Fase 6d): `check` → `fact_note` wajib satu kalimat Indonesia tentang yang belum pasti; `low` → `fact_note` dibuang. Awalan mekanisme di `angle` seperti "Hidden logic:" dibuang validator.
- §4.1: prompt `ideas.from_topic` bila topic terisi, `ideas.discover` bila hanya kategori. Bila `category_id` project kosong dan `suggested_category` valid → isi dengan `category_source = suggested`. Gerbang A: endpoint select mengisi `selected_idea_id` lalu memanggil `reconcile`, yang meng-enqueue job `script`.
- §5.2 `StructuredLLM`: mode dari `caps.structured`; parse membersihkan `<think>…</think>`, code fence, objek JSON terluar, koma berlebih, escape tidak valid; jawaban terpotong (`finish_reason=length`) diminta ulang dengan token 2× (maks 16000); gagal validasi → satu retry dengan balasan + pesan error spesifik; masih gagal → `MalformedOutputError`, lalu provider berikutnya sesuai prioritas.
- §5.3 `ProviderRouter.candidates(capability, project)`: override project, lalu provider `enabled` terurut `priority`. Untuk llm daftar penuh dipakai sebagai rantai cadangan.
- §5.4 seed: router LLM dari `.env` (`LLM_BASE_URL`, `LLM_MODEL`) adapter `openai_compatible`, quirks `{"system_role": false, "structured": "json_object", "strips_think": true, "max_concurrency": 4}`. (Jembatan sesi Muse bersifat OpenAI-compatible, jadi `LLM_BASE_URL` kelak bisa menunjuk ke sana.)
- §5.5 kelas error di `app/providers/errors.py`, masing-masing membawa `message_id` (Indonesia) dan `detail` ≤ 500 karakter: `AuthError` (401/403, tidak retryable), `RateLimitError` (429, retryable, `retry_after`), `ProviderTimeout` (retryable = `caps.retry_safe`), `ContentPolicyError` (tidak), `BadRequestError` (tidak), `ServerError` (5xx/koneksi, retryable), `MalformedOutputError` (retryable sekali).
- §6.1: file prompt `app/prompts/tasks/<task>/v<N>.md`, `blocks/<name>.md`, `categories/<slug>.md`, `formats/<slug>.md`; isi task dibagi penanda `## [system]` dan `## [user]`; kontrak output lewat `{{ output_contract }}` yang dibangkitkan dari model Pydantic (§3 kalimat pertama).
- §6.2 sinkronisasi versi: `content_hash` belum ada → `prompt_version` baru `source=builtin`; selama versi aktif berasal dari `builtin`, versi aktif mengikuti file vN terbesar di disk.
- §6.3 `PromptService.render(task, inputs) -> RenderedPrompt(task, messages, version_id, temperature, max_tokens, output_model)`.
- §9 rute Fase 2: `GET/POST /projects`, `GET/PATCH /projects/{id}`, `POST /projects/{id}/ideas/generate`, `GET /projects/{id}/ideas`, `POST /ideas/{id}/select`, `GET /categories`, `GET /formats`, `GET /providers` (tanpa rahasia: `has_api_key`, `api_key_hint` 4 karakter terakhir terenkripsi tidak pernah tampil mentah — hint diambil dari kunci yang disimpan terenkripsi? Tidak: hint disimpan tidak bisa dari ciphertext; keputusan fase ini: `api_key_hint` = 4 karakter terakhir disimpan sebagai kolom turunan saat kunci ditulis — lihat Task 3 ruling di ledger bila menyimpang).
- Semua pesan error pengguna berbahasa Indonesia; bentuk error standar Fase 1 dipakai ulang.

## Keputusan lingkup fase ini (dicatat agar tidak mengambang)

1. **`llm_raw` ditunda ke Fase 4.** §5.2 meminta prompt terrender + respons mentah disimpan sebagai aset `llm_raw`, tapi tabel `asset` baru lahir di Fase 4 (§2.1 catatan migrasi). Fase ini: prompt + respons mentah disimpan di `generation_job.result` milik job pemanggil (`llm_raw: {prompt, raw}` dipotong 20.000 karakter) — cukup untuk debug, dan dipindah ke aset di Fase 4.
2. **Rantai `script` belum di-enqueue.** Handler `script` lahir di Fase 3. `reconcile` Fase 2 mengimplementasikan cabang Gerbang A sebagai: bila ide terpilih ada, belum ada script untuk ide itu, DAN handler `script` terdaftar di `HANDLERS` → enqueue. Di Fase 2 cabang ini tidak men-enqueue apa pun (handler belum ada) dan otomatis aktif di Fase 3 tanpa ubah kode reconcile.
3. **CRUD provider penuh = Fase 6.** Fase ini hanya seed + `GET /providers` + `GET /providers/adapters`. `POST /providers/{id}/test` sudah ada jalurnya lewat job `provider_test` Fase 1 untuk provider fake; test untuk provider LLM memakai job `ideas` dry-run.
4. **Kategori/format awal** (file seed, bisa diedit pemilik — memang itu gunanya sinkronisasi file): kategori `animals` (Hewan, normal), `science` (Sains & Alam, normal), `health` (Kesehatan, strict), `history` (Sejarah, normal), `daily-life` (Kehidupan Sehari-hari, normal); format `myth-vs-fact` (Mitos vs Fakta), `did-you-know` (Tahukah Kamu), `top-list` (Daftar Top). Slug Inggris, nama tampil Indonesia (mengikuti contoh §2.1).
5. **FakeLLM untuk `ideas`**: mengembalikan fixture 8 ide berbahasa Indonesia yang judulnya memakai topik dari prompt (baris `Topik: …`), supaya kriteria "8 ide di UI" terbukti dalam dry-run tanpa endpoint LLM sungguhan. Jalur minimal-schema tetap jadi cadangan.

## Konvensi global

- Warisan Fase 1 berlaku penuh: ULID, UTC, awalan `/api`, bentuk error standar, pesan Indonesia, TDD (tes gagal dulu), commit per task, `.gitignore` sudah mencakup `.venv`/`node_modules`/`storage` — `git add` tidak akan mengulangi insiden venv.
- Tambahkan `pyyaml` ke dependencies backend (`pyproject.toml`) dan install ke venv VM.
- Migrasi baru: `0002` (revisi setelah `0001`).
- Branch: `feat/fase-2-domain-ide` (dari ujung `feat/fase-1-kerangka`).

---

### Task 1: Model domain + migrasi 0002

**File:**
- Ubah: `backend/app/db/models.py` (tambah model di bawah)
- Buat: `backend/alembic/versions/0002_domain.py`
- Buat: `backend/tests/test_domain_models.py`

**Antarmuka:**
- Menghasilkan: `Category`, `Format`, `Project`, `ContentIdea`, `Provider`, `PromptTemplate`, `PromptVersion` (SQLAlchemy, `Base` yang sama).
- `Project`: kolom sesuai "Keputusan" di atas; validasi tingkat model tidak dipakai — constraint topic/category dicek di API (Task 6) supaya pesan error-nya Indonesia; tetap tambahkan `CheckConstraint("topic IS NOT NULL OR category_id IS NOT NULL", name="ck_project_topic_or_category")` di tabel.

- [ ] **Langkah 1: Tes model**

```python
# backend/tests/test_domain_models.py
import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Category, ContentIdea, Project, PromptTemplate, PromptVersion, Provider


async def test_project_requires_topic_or_category(session):
    session.add(Project(title="Tanpa topik"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_project_defaults(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.commit()
    assert project.language == "id-ID"
    assert (project.target_min_s, project.target_max_s) == (30, 40)
    assert project.settings == {}


async def test_idea_batch_rows(session):
    project = Project(title="Cicak", topic="cicak")
    session.add(project)
    await session.flush()
    session.add(ContentIdea(project_id=project.id, batch=1, position=1,
                            title="Judul ide yang cukup panjang", job_id="01JTEST"))
    await session.commit()


async def test_category_slug_unique(session):
    session.add(Category(slug="animals", name="Hewan"))
    await session.commit()
    session.add(Category(slug="animals", name="Duplikat"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_prompt_version_immutable_shape(session):
    template = PromptTemplate(key="ideas.from_topic", kind="task")
    session.add(template)
    await session.flush()
    version = PromptVersion(template_id=template.id, version=1, source="builtin",
                            content="isi", frontmatter={}, content_hash="abc")
    session.add(version)
    await session.commit()
    template.active_version_id = version.id
    await session.commit()


async def test_provider_defaults(session):
    provider = Provider(name="Fake", capability="llm", adapter="fake")
    session.add(provider)
    await session.commit()
    assert provider.enabled is True and provider.quirks == {}
```

- [ ] **Langkah 2: Jalankan tes, pastikan gagal**

Jalankan: `cd backend && .venv/bin/python -m pytest tests/test_domain_models.py -q`
Hasil yang diharapkan: FAIL (ImportError: Category dsb. belum ada).

- [ ] **Langkah 3: Implementasi model**

Tambahkan ke `backend/app/db/models.py` (semua `id` ULID `default=new_ulid`, waktu `default=utcnow`; `updated_at` memakai `onupdate=utcnow`):

```python
class Category(Base):
    __tablename__ = "category"
    id, slug (String(64), unique, index), name (String(128)), description (String(500), default ""),
    fact_check (String(16), default "normal"), prompt_template_id (String(26), nullable),
    enabled (Boolean, default True), created_at, updated_at

class Format(Base):  # __tablename__ = "format"; sama seperti Category tanpa fact_check
    ...

class Provider(Base):
    __tablename__ = "provider"
    id, name (String(128)), capability (String(16)), adapter (String(64)),
    base_url (String(255), nullable), api_key_encrypted (LargeBinary, nullable),
    api_key_hint (String(4), nullable), default_model (String(128), nullable),
    quirks (JSON, default dict), enabled (Boolean, default True), priority (Integer, default 100),
    created_at, updated_at

class PromptTemplate(Base):
    __tablename__ = "prompt_template"
    id, key (String(128), unique, index), kind (String(16)), active_version_id (String(26), nullable),
    created_at, updated_at

class PromptVersion(Base):
    __tablename__ = "prompt_version"
    id, template_id (FK prompt_template.id, index), version (Integer), source (String(16), default "builtin"),
    content (Text), frontmatter (JSON, default dict), content_hash (String(64), index), created_at
    # UniqueConstraint(template_id, version), UniqueConstraint(template_id, content_hash)

class Project(Base):
    __tablename__ = "project"
    __table_args__ = (CheckConstraint("topic IS NOT NULL OR category_id IS NOT NULL",
                                      name="ck_project_topic_or_category"),)
    id, title (String(255)), topic (String(500), nullable), category_id (FK category.id, nullable),
    category_source (String(16), nullable), format_id (FK format.id, nullable),
    language (String(8), default "id-ID"), target_min_s (Integer, default 30),
    target_max_s (Integer, default 40), selected_idea_id (String(26), nullable),
    settings (JSON, default dict), created_at, updated_at

class ContentIdea(Base):
    __tablename__ = "content_idea"
    id, project_id (FK project.id, index), batch (Integer), position (Integer),
    title (String(255)), angle (Text, default ""), hook (Text, default ""),
    why_it_works (Text, default ""), suggested_category_slug (String(64), nullable),
    fact_risk (String(8), nullable), fact_note (Text, nullable),
    job_id (String(26), index), created_at
    # UniqueConstraint(project_id, batch, position)
```

Migrasi `0002_domain.py`: `create_table` untuk ketujuh tabel + constraint/check yang sama persis (termasuk partial index tidak ada di fase ini), `downgrade` membuang dalam urutan terbalik.

- [ ] **Langkah 4: Hijau + migrasi terverifikasi**

Jalankan: `.venv/bin/python -m pytest tests/ -q` (semua lulus) dan `DATABASE_URL="sqlite+aiosqlite:////tmp/f2.db" .venv/bin/alembic upgrade head` lalu cek 10 tabel ada (3 lama + 7 baru).

- [ ] **Langkah 5: Commit**

```bash
git add backend && git commit -m "feat(fase-2): model domain proyek, ide, provider, prompt"
```

---

### Task 2: File prompt + PromptService

**File:**
- Buat: `backend/app/prompts/tasks/ideas.from_topic/v1.md`, `backend/app/prompts/tasks/ideas.discover/v1.md`
- Buat: `backend/app/prompts/blocks/output_rules.md` (blok aturan umum ide: bahasa, hook, tanpa membuka jawaban)
- Buat: `backend/app/prompts/categories/{animals,science,health,history,daily-life}.md`
- Buat: `backend/app/prompts/formats/{myth-vs-fact,did-you-know,top-list}.md`
- Buat: `backend/app/services/prompts.py` (parser frontmatter, sinkronisasi, render, kontrak output)
- Buat: `backend/app/domain/__init__.py`, `backend/app/domain/llm_outputs.py` (baru `IdeasOutput` di Task 4 — Task ini hanya butuh registry nama→model untuk kontrak; buat file-nya di sini dengan `IdeasOutput` sekalian mengikuti §3.1 supaya Task 4 tinggal menambah validasi bisnis)
- Ubah: `backend/pyproject.toml` (+ `pyyaml`), `backend/app/main.py` dan `backend/app/worker.py` (panggil sinkronisasi saat startup)
- Buat: `backend/tests/test_prompts.py`

**Antarmuka:**
- `parse_frontmatter(text: str) -> tuple[dict, str]` — YAML di antara `---`, sisa = isi.
- `content_hash(text: str) -> str` — sha256 hex dari teks persis.
- `async def sync_prompts(session, root: Path | None = None) -> dict` — memindai `tasks/`, `blocks/`, `categories/`, `formats/`; membuat/memperbarui `prompt_template` + `prompt_version` (aturan §6.2), dan baris `category`/`format` dari frontmatter + isi file (isi file = aturan yang dirender ke `{{ category.rules }}`; simpan `content` di versi prompt template berkunci `category.<slug>` / `format.<slug>`, dan `prompt_template_id` category/format menunjuk template itu). Mengembalikan ringkasan `{"templates": n, "versions": n, "categories": n, "formats": n}`.
- `class PromptService:` `__init__(self, session)`; `async def render(self, task: str, inputs: dict) -> RenderedPrompt`.
- `@dataclass RenderedPrompt: task: str; messages: list[Message]; version_id: str; temperature: float; max_tokens: int; output_model: type[BaseModel] | None`.
- `output_contract(model: type[BaseModel]) -> str` — teks kontrak dari field model (nama, tipe, enum, batas panjang dari `Field` constraints, contoh dari `json_schema_extra` bila ada). Dipakai template lewat variabel `output_contract` yang diisi `render` otomatis bila task punya `output`.
- Frontmatter task `ideas.from_topic` v1: `task: ideas.from_topic`, `version: 1`, `inputs: [topic, category, format, language]`, `output: IdeasOutput`, `temperature: 0.9`, `max_tokens: 4000`. Isi memuat `## [system]` dan `## [user]`; bagian user memuat baris `Topik: {{ topic }}` (dipakai FakeLLM Task 5), `{{ category.rules }}`/`{{ format.rules }}` bila ada, dan `{{ output_contract }}`. Instruksi Inggris, contoh Indonesia (§6.1).
- Registry output: `OUTPUT_MODELS: dict[str, type[BaseModel]]` di `llm_outputs.py` memetakan nama frontmatter (`IdeasOutput`) ke kelas.

- [ ] **Langkah 1: Tes PromptService**

```python
# backend/tests/test_prompts.py
from app.domain.llm_outputs import IdeasOutput
from app.services.prompts import PromptService, output_contract, parse_frontmatter, sync_prompts


def test_parse_frontmatter():
    meta, body = parse_frontmatter("---\nname: Hewan\nversion: 1\n---\nisi teks")
    assert meta["name"] == "Hewan" and body == "isi teks"


def test_output_contract_lists_fields_and_limits():
    contract = output_contract(IdeasOutput)
    assert "ideas" in contract and "title" in contract


async def test_sync_creates_templates_categories_formats(session):
    summary = await sync_prompts(session)
    await session.commit()
    assert summary["categories"] == 5 and summary["formats"] == 3
    again = await sync_prompts(session)  # idempoten: hash sama, tidak ada versi baru
    assert again["versions"] == 0


async def test_render_ideas_prompt(session):
    await sync_prompts(session)
    await session.commit()
    service = PromptService(session)
    rendered = await service.render("ideas.from_topic", {
        "topic": "cicak", "language": "id-ID", "category": None, "format": None})
    assert rendered.output_model is IdeasOutput
    assert rendered.version_id
    joined = "\n".join(m.content for m in rendered.messages)
    assert "cicak" in joined and "Topik:" in joined
    assert rendered.messages[0].role == "system"
```

- [ ] **Langkah 2: RED** — `pytest tests/test_prompts.py -q` gagal (modul belum ada).

- [ ] **Langkah 3: Tulis file prompt + `IdeasOutput` + service**

`IdeasOutput` (§3.1, validasi bisnis penuh di Task 4 — di sini struktur + batas field):

```python
# backend/app/domain/llm_outputs.py
from pydantic import BaseModel, Field

class IdeaItem(BaseModel):
    title: str = Field(min_length=20, max_length=90)
    angle: str
    hook: str
    why_it_works: str
    fact_risk: str = Field(pattern="^(low|check)$")
    fact_note: str | None = None

class IdeasOutput(BaseModel):
    suggested_category: str | None = None
    ideas: list[IdeaItem]

OUTPUT_MODELS = {"IdeasOutput": IdeasOutput}
```

`services/prompts.py`:
- `_iter_prompt_files(root)`: tasks → key dari nama folder, kind `task`; blocks → `block.<name>`; categories → `category.<slug>`; formats → `format.<slug>`. Untuk task, versi dari nama file `v<N>.md`, N terbesar yang aktif untuk source builtin.
- Sinkronisasi per file: hash isi file persis (termasuk frontmatter); versi baru hanya bila `(template_id, content_hash)` belum ada; aktifkan versi file terbesar bila versi aktif saat ini `builtin` (§6.2).
- Baris `category`: upsert by `slug` dari frontmatter (`name`, `description`, `fact_check`), `prompt_template_id` = template `category.<slug>`. `format` sama tanpa `fact_check`.
- `render`: ambil template + versi aktif; pisah isi dengan penanda `## [system]` / `## [user]`; Jinja render tiap bagian dengan `inputs` + `output_contract` (bila output) + objek `category`/`format` (dict `{name, rules}` — rules = isi file kategori/format dari versi aktif template-nya; diisi pemanggil lewat inputs sebagai dict atau None; PromptService menormalisasi None → rules kosong). Variabel tak dikenal → Jinja `StrictUndefined` melempar → dibungkus `ValueError` pesan Indonesia.
- Startup: `main.serve()` dan `worker._main()` membuka sesi dan memanggil `sync_prompts` sebelum melayani (kegagalan sinkronisasi = gagal start, pesan jelas).

- [ ] **Langkah 4: Hijau** — `pytest tests/ -q` semua lulus; jalankan sinkronisasi sekali terhadap DB dev dan pastikan `sqlite3 storage/app.db "select key from prompt_template"` memuat `ideas.from_topic`, `ideas.discover`, 5 `category.*`, 3 `format.*`, `block.output_rules`.

- [ ] **Langkah 5: Commit** — `git commit -m "feat(fase-2): file prompt dan PromptService"`

---

### Task 3: Error provider, adapter LLM OpenAI-compatible, router, seed

**File:**
- Buat: `backend/app/providers/errors.py`
- Buat: `backend/app/providers/llm/openai_compatible.py`
- Buat: `backend/app/providers/router.py`
- Buat: `backend/app/services/crypto.py` (Fernet dari `APP_SECRET_KEY` — kunci Fernet diturunkan via sha256 dari secret agar format `.env` tetap satu string bebas; fungsi `encrypt_secret(str) -> bytes`, `decrypt_secret(bytes) -> str`)
- Ubah: `backend/app/providers/registry.py` (+ `("llm", "openai_compatible")`), `backend/app/providers/base.py` (TextResult + `finish_reason: str | None`), `backend/app/config.py` (+ `llm_base_url: str | None`, `llm_model: str | None`, `llm_api_key: str | None`)
- Buat: `backend/app/services/providers_seed.py`
- Buat: `backend/tests/test_llm_adapter.py`, `backend/tests/test_router_seed.py`

**Antarmuka:**
- `errors.py`: kelas-kelas §5.5; basis `ProviderError(Exception)` dengan atribut `retryable: bool`, `message_id: str`, `detail: str | None`; `RateLimitError` + `retry_after: float | None`. `message_id` bawaan per kelas dalam Bahasa Indonesia (mis. AuthError → "Kunci API provider ditolak. Periksa pengaturan provider.").
- `class OpenAICompatibleLLM`: `__init__(self, *, base_url: str, api_key: str | None, default_model: str | None, quirks: dict | None = None)`; `caps` efektif = `LLMCaps` bawaan (`structured="json_object"`) ditimpa quirks yang dikenal (`structured`, `system_role`, `strips_think`, `timeout_s`, `max_concurrency`, `retry_safe`, `extra_body`). `async def generate_text(self, req: TextRequest, ctx=None) -> TextResult`:
  - body: `model = req.model or default_model`, `messages` (bila `system_role` false: gabung semua pesan system ke awal pesan user pertama), `temperature`, `max_tokens`; `response_format` = `{"type": "json_schema", "json_schema": {...}}` bila caps `json_schema` dan `req.response_schema` ada, `{"type": "json_object"}` bila `json_object`; `extra_body` digabung.
  - POST `{base_url}/chat/completions`, header `Authorization: Bearer <key>` bila ada. Timeout dari quirks `timeout_s` (bawaan 120).
  - respons sukses: `text = choices[0].message.content`, `finish_reason = choices[0].finish_reason`, usage dari `usage.prompt_tokens/completion_tokens`, `latency_ms` diukur.
  - pemetaan error §5.5 dari status HTTP; body error dipotong 500 karakter ke `detail`; timeout httpx → `ProviderTimeout(retryable=caps.retry_safe bawaan True untuk adapter ini)`.
- `ProviderRouter(session)`: `async def candidates(self, capability: str, project=None) -> list[Provider]` — provider `enabled` kemampuan itu terurut `priority, created_at`; untuk project dengan override (llm belum punya kolom override di Fase 2 → abaikan, parameter diterima untuk bentuk §5.3). `async def build_llm(self, provider: Provider) -> LLMProvider` — instansiasi dari `ADAPTERS[("llm", provider.adapter)]`: `fake` → `FakeLLM()`; `openai_compatible` → konstruktor di atas dengan kunci terdekripsi.
- `async def seed_providers(session, settings) -> None`: idempoten berdasar `(capability, adapter, name)`:
  - selalu: `LLM Fake (dry-run)`, llm/fake, enabled, priority 100 (cadangan terakhir).
  - bila `settings.llm_base_url`: `Router LLM`, llm/openai_compatible, base_url + default_model dari env, kunci terenkripsi bila ada, quirks persis §5.4, enabled, priority 10.
  Dipanggil saat startup setelah `sync_prompts`.

- [ ] **Langkah 1: Tes adapter (respx) + router/seed**

```python
# backend/tests/test_llm_adapter.py (inti)
import httpx, respx
from app.providers.errors import AuthError, ServerError
from app.providers.llm.openai_compatible import OpenAICompatibleLLM

@respx.mock
async def test_generate_text_json_object_mode():
    route = respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5}, "model": "m1"}))
    llm = OpenAICompatibleLLM(base_url="http://llm.test/v1", api_key="k", default_model="m1",
                              quirks={"system_role": False, "structured": "json_object"})
    result = await llm.generate_text(TextRequest(messages=[
        Message(role="system", content="Aturan."), Message(role="user", content="Halo")]), None)
    assert result.text == '{"ok": true}' and result.finish_reason == "stop"
    body = route.calls[0].request.read()
    assert b'"response_format":{"type":"json_object"}' in body
    assert b'"Aturan.' in body  # system digabung ke user pertama

@respx.mock
async def test_http_errors_map_to_provider_errors():
    respx.post("http://llm.test/v1/chat/completions").mock(return_value=httpx.Response(401, text="no"))
    llm = OpenAICompatibleLLM(base_url="http://llm.test/v1", api_key="salah", default_model="m1")
    with pytest.raises(AuthError):
        await llm.generate_text(TextRequest(messages=[Message(role="user", content="x")]), None)
```

```python
# backend/tests/test_router_seed.py (inti)
async def test_seed_creates_fake_and_env_router(session):
    settings = Settings(app_secret_key="x" * 32, llm_base_url="http://llm.test/v1", llm_model="m1")
    await seed_providers(session, settings); await session.commit()
    await seed_providers(session, settings); await session.commit()  # idempoten
    router = ProviderRouter(session)
    candidates = await router.candidates("llm")
    assert [p.name for p in candidates] == ["Router LLM", "LLM Fake (dry-run)"]
    built = await router.build_llm(candidates[0])
    assert isinstance(built, OpenAICompatibleLLM)
```

- [ ] **Langkah 2: RED** — kedua file tes gagal import.

- [ ] **Langkah 3: Implementasi** sesuai antarmuka di atas. `TextResult.finish_reason` default `None`; `FakeLLM` tidak berubah perilakunya (finish_reason tetap None). Kunci quirks tak dikenal di adapter diabaikan (penolakan kunci tak dikenal berlaku saat menyimpan lewat API — Fase 6).

- [ ] **Langkah 4: Hijau** — `pytest tests/ -q`.

- [ ] **Langkah 5: Commit** — `git commit -m "feat(fase-2): adapter LLM OpenAI-compatible, router, dan seed provider"`

---

### Task 4: StructuredLLM + aturan bisnis IdeasOutput

**File:**
- Buat: `backend/app/services/structured_llm.py`
- Ubah: `backend/app/domain/llm_outputs.py` (+ validasi bisnis IdeasOutput)
- Buat: `backend/tests/test_structured_llm.py`

**Antarmuka:**
- `clean_json_text(raw: str) -> str` — buang blok `<think>…</think>`, ambil isi code fence bila ada, ambil substring dari `{` pertama sampai `}` terakhir yang seimbang, perbaiki koma sebelum `}`/`]`, perbaiki escape tidak valid (`\` yang bukan escape JSON sah → `\\`). Diekspor untuk tes satuan.
- `validate_ideas(output: IdeasOutput, valid_category_slugs: set[str]) -> IdeasOutput` — aturan §3.1: tepat 8 ide (kurang/lebih → `ValueError` pesan spesifik Indonesia); rasio kemiripan token judul berpasangan < 0,8 (token = kata huruf kecil tanpa tanda baca; rasio = |irisan| / |union|; pelanggaran → ValueError menyebut dua judul); `suggested_category` bukan slug sah → `None`; per ide: `fact_risk == "check"` tanpa `fact_note` → ValueError; `low` → `fact_note = None`; `angle`: buang awalan pola `^[A-Za-z ]+:\s*` hanya bila awalan cocok daftar mekanisme ("Hidden logic", "Curiosity gap", "Rahasia", dsb. — daftar konstan `ANGLE_PREFIXES`); judul di-trim.
- `class StructuredLLM`: `__init__(self, candidates: list[tuple[Provider, LLMProvider]], prompts: PromptService)` — candidates dari router (baris provider + adapter terbangun).
  - `async def generate(self, *, task: str, inputs: dict, output_model: type[BaseModel], ctx=None, validate=None) -> StructuredResult`
  - `@dataclass StructuredResult: data: BaseModel; provider: Provider; model: str; prompt_version_id: str; raw_text: str; prompt_text: str; attempts: int` (`prompt_text` = gabungan messages terrender, untuk disimpan pemanggil sesuai Keputusan 1).
  - Alur per kandidat (§5.2): render prompt → `TextRequest(messages, temperature, max_tokens, response_schema=output_model bila caps structured == json_schema)` → panggil → bila `finish_reason == "length"`: ulang sekali dengan `max_tokens = min(max_tokens*2, 16000)` dan pesan tambahan user "Balasan sebelumnya terpotong…" → parse `clean_json_text` + `json.loads` → `output_model.model_validate` → `validate(data)` bila diberikan → sukses: kembalikan. Gagal parse/validasi: satu retry dengan messages + balasan model (role assistant) + pesan user berisi error spesifik ("Jawaban tidak valid: <error>. Perbaiki dan kirim ulang JSON lengkap.") → masih gagal: catat `MalformedOutputError`, lanjut kandidat berikut. Semua kandidat gagal → naikkan `MalformedOutputError` terakhir. Error provider selain malformed (Auth/Server/dsb.) langsung naik (tidak pindah kandidat) — sesuai §5.2 yang hanya menyebut malformed sebagai pemicu pindah.

- [ ] **Langkah 1: Tes**

```python
# backend/tests/test_structured_llm.py (inti)
from app.domain.llm_outputs import IdeasOutput
from app.services.structured_llm import StructuredLLM, clean_json_text, validate_ideas

def ideas_payload(n=8, **kw): ...  # pembangun dict ide valid

class StubLLM:
    caps = LLMCaps(structured="json_object")
    def __init__(self, replies): self.replies = list(replies); self.calls = 0
    async def generate_text(self, req, ctx=None):
        self.calls += 1
        return self.replies.pop(0)

def test_clean_json_text_strips_think_and_fence():
    raw = "<think>mikIr</think>```json\n{\"a\": 1,}\n```"
    assert json.loads(clean_json_text(raw)) == {"a": 1}

def test_validate_ideas_rules():
    out = IdeasOutput.model_validate(ideas_payload())
    validate_ideas(out, {"animals"})  # lolos
    with pytest.raises(ValueError):
        validate_ideas(IdeasOutput.model_validate(ideas_payload(n=7)), {"animals"})

async def test_retry_with_error_feedback_then_success(session): ...
    # StubLLM membalas JSON rusak sekali, lalu valid → attempts == 2, data IdeasOutput

async def test_malformed_falls_through_to_next_candidate(session): ...
    # kandidat 1 selalu rusak → MalformedOutputError dicatat, kandidat 2 valid → dipakai

async def test_truncated_reply_retried_with_double_tokens(session): ...
    # finish_reason "length" → panggilan kedua max_tokens lebih besar
```

(PromptService untuk tes: pakai sesi tes + `sync_prompts` sungguhan; Provider baris dibuat manual di tes.)

- [ ] **Langkah 2: RED**.

- [ ] **Langkah 3: Implementasi** sesuai antarmuka. Perhatian: `IdeasOutput.ideas` batas tepat 8 ditegakkan di `validate_ideas`, BUKAN di Pydantic `Field` — supaya pesan retry ke model menyebut jumlah persis ("Ada 7 ide, wajib tepat 8").

- [ ] **Langkah 4: Hijau** — `pytest tests/ -q`.

- [ ] **Langkah 5: Commit** — `git commit -m "feat(fase-2): StructuredLLM dan aturan bisnis ide"`

---

### Task 5: Handler job `ideas`, FakeLLM fixture, reconcile Gerbang A

**File:**
- Ubah: `backend/app/providers/llm/fake.py` (+ fixture ideas)
- Buat: `backend/app/jobs/ideas.py` (handler), daftarkan di `backend/app/jobs/handlers.py`
- Ubah: `backend/app/services/reconcile.py` (cabang Gerbang A sesuai Keputusan 2)
- Ubah: `backend/app/api/jobs.py` — TIDAK: `SUPPORTED_JOB_TYPES` untuk POST /jobs tetap `provider_test`; job `ideas` dibuat lewat endpoint project (Task 6).
- Buat: `backend/tests/test_ideas_job.py`

**Antarmuka:**
- FakeLLM: bila `req.response_schema is IdeasOutput` → kembalikan fixture 8 ide (judul/angle/hook/why_it_works Indonesia, 2 ide `fact_risk: check` + `fact_note`, sisanya `low`), topik diekstrak dari baris `Topik: …` pada messages (fallback "topik ini") dan disisipkan ke judul-judul templat (judul tetap 20–90 karakter dan saling berbeda cukup jauh agar lolos rasio < 0,8). Schema lain → perilaku lama.
- `async def run_ideas(job, factory) -> dict`:
  1. Muat project; sudah ada `ContentIdea` dengan `job_id == job.id` → kembalikan ringkasan batch itu tanpa memanggil LLM (idempotensi §2.1).
  2. Tentukan task: `topic` terisi → `ideas.from_topic`, else `ideas.discover`. Inputs: `topic`, `category`/`format` sebagai dict `{name, rules}` dari versi aktif template kategori/format project (atau None), `language`.
  3. `candidates = ProviderRouter(session).candidates("llm", project)` difilter yang adapter-nya bisa dibangun; kosong → `LookupError("Belum ada provider LLM aktif…")` dibungkus error job kind `NoLlmProvider` (lempar `ProviderError` khusus? Pakai `RuntimeError` dengan atribut `retryable = False` dan kind dicatat dari nama kelas — buat kelas `NoLlmProviderError(Exception)` di handler dengan `retryable=False`; worker mencatat kind dari `type(exc).__name__` = `NoLlmProviderError`. Hmm — spec memakai kind `NoLlmProvider` (§4.14). Worker Fase 1 memakai nama kelas sebagai kind; tambahkan dukungan atribut `kind` opsional pada exception di `worker._execute`: `error.kind = getattr(exc, "kind", type(exc).__name__)`. Ubah worker sebaris itu di task ini + tes regresi cepat.)
  4. `StructuredLLM.generate(task, inputs, IdeasOutput, validate=lambda out: validate_ideas(out, slugs_kategori_aktif))`.
  5. Tulis batch: `batch = (max batch project atau 0) + 1`, 8 baris `position` 1..8 dengan `job_id=job.id`; project tanpa kategori + `suggested_category` valid → set `category_id` + `category_source="suggested"`.
  6. `usage_record` capability `llm` dari usage panggilan terakhir; set `job.prompt_version_id`, `job.provider_id`, `job.model` (lewat sesi sendiri sebelum return — pola handler `provider_test`).
  7. Return `{"batch": n, "idea_ids": [...], "llm_raw": {"prompt": prompt_text, "raw": raw_text}}` (Keputusan 1).
- `reconcile(project_id)`: muat project; bila `selected_idea_id` terisi dan belum ada baris script untuk ide itu (tabel `script` belum ada di Fase 2 → perlakukan "belum ada" sebagai True) dan `"script" in HANDLERS` → `enqueue(type="script", project_id=..., input={"idea_id": ...})`. Fase 2: kondisi handler selalu False → tidak ada aksi; log debug saja.

- [ ] **Langkah 1: Tes handler**

```python
# backend/tests/test_ideas_job.py (inti)
async def test_ideas_job_writes_batch_of_eight(session):
    await sync_prompts(session); await seed_providers(session, settings_tanpa_env_llm())
    project = Project(title="Cicak", topic="cicak")
    session.add(project); await session.commit()
    job = await enqueue(session, type="ideas", input={}, project_id=project.id)
    await session.commit()
    worker = Worker(session_factory=factory_of(session))
    assert await worker.run_once() is True
    ideas = (await session.execute(select(ContentIdea).where(
        ContentIdea.project_id == project.id).order_by(ContentIdea.position))).scalars().all()
    assert len(ideas) == 8 and ideas[0].batch == 1 and all(i.job_id == job.id for i in ideas)
    refreshed = await session.get(GenerationJob, job.id); await session.refresh(refreshed)
    assert refreshed.status == "completed" and refreshed.provider_id

async def test_ideas_job_idempotent_on_retry(session):
    # jalankan handler dua kali untuk job yang sama (simulasi worker mati sesudah tulis):
    # batch tetap 1 dan LLM tidak dipanggil kedua kali (result.llm_raw sama / jumlah baris tetap 8)
```

- [ ] **Langkah 2: RED**.

- [ ] **Langkah 3: Implementasi** sesuai antarmuka (+ ubahan sebaris worker untuk `kind`).

- [ ] **Langkah 4: Hijau** — `pytest tests/ -q`.

- [ ] **Langkah 5: Commit** — `git commit -m "feat(fase-2): job ideas, fixture FakeLLM, reconcile Gerbang A"`

---

### Task 6: API projects, kategori, format, ide, providers

**File:**
- Buat: `backend/app/api/projects.py`, `backend/app/api/catalog.py` (categories + formats + providers), daftarkan router di `backend/app/main.py`
- Buat: `backend/tests/test_projects_api.py`

**Antarmuka:**
- Skema keluar:
  - `CategoryOut(id, slug, name, description, fact_check, enabled)`, `FormatOut` (tanpa fact_check).
  - `ProviderOut(id, name, capability, adapter, base_url, default_model, enabled, priority, has_api_key, api_key_hint)` — tidak pernah memuat kunci.
  - `ProjectOut(id, title, topic, category_id, category_source, format_id, language, target_min_s, target_max_s, selected_idea_id, settings, created_at, updated_at, idea_batches: int, idea_count: int)` — hitungan dari query agregat ringan.
  - `IdeaOut(id, project_id, batch, position, title, angle, hook, why_it_works, suggested_category_slug, fact_risk, fact_note, created_at)`.
  - `IdeasGenerateOut(job: JobOut, created: bool)` mengikuti pola spec "job aktif dikembalikan dengan created=false".
- Rute:
  - `GET /api/categories`, `GET /api/formats` — hanya `enabled`, urut nama.
  - `GET /api/providers`, `GET /api/providers/adapters` (daftar dari `ADAPTERS`: capability, adapter, `dry_run = adapter == "fake"`, caps bawaan kelas sebagai dict).
  - `POST /api/projects` (201): body `{title?, topic?, category_id?, format_id?, language?}` — `title` kosong → pakai `topic`, lalu nama kategori. `topic` dan `category_id` dua-duanya kosong → 422 `ProjectNeedsTopicOrCategory` ("Isi topik atau pilih kategori dulu."). `category_id` terisi → `category_source = "user"`. FK tidak ditemukan → 422 `InvalidCategory` / `InvalidFormat` pesan Indonesia. `target_min_s/max_s` tidak diterima di create (bawaan), diubah lewat PATCH.
  - `GET /api/projects` urut `updated_at` desc; `GET /api/projects/{id}` 404 standar.
  - `PATCH /api/projects/{id}`: subset Fase 2 `{title, topic, category_id, format_id, language, target_min_s, target_max_s, settings}` — validasi `target_min_s < target_max_s` (422 `InvalidProject`), settings digabung (merge kunci), bukan diganti utuh. Setelah PATCH yang mengubah `selected_idea_id`? Tidak diterima di PATCH — pemilihan hanya lewat endpoint select.
  - `POST /api/projects/{id}/ideas/generate` (202): bila ada job `ideas` aktif untuk project → kembalikan job itu `created=false`; selain itu enqueue (input `{}` — semua konteks dibaca handler dari project), `created=true`. Project tanpa topic dan tanpa kategori tidak mungkin ada (constraint), jadi selalu sah.
  - `GET /api/projects/{id}/ideas`: semua batch, urut `batch, position`; sertakan `batches: [{batch, created_at, job_id}]`? Bentuk respons: `list[IdeaOut]` datar + header batch ada di tiap baris — UI mengelompokkan. (Jaga sederhana: list datar.)
  - `POST /api/ideas/{id}/select`: set `project.selected_idea_id`, `project.title` = judul ide bila title project masih sama dengan topic awal? Spec §2.1: title "awalnya dari topik, lalu dari ide terpilih" → select selalu menyalin `title = idea.title` (pemilik bisa PATCH sesudahnya). Panggil `reconcile(project.id)` sesudah commit. Kembalikan `ProjectOut`.
- Pakai ulang `SessionDep`, `AppError`, `NotFoundError` dari Fase 1.

- [ ] **Langkah 1: Tes API**

```python
# backend/tests/test_projects_api.py (inti; fixture app seperti test_api.py + sync_prompts + seed)
def test_create_project_needs_topic_or_category(client):  # 422 kind ProjectNeedsTopicOrCategory
def test_create_and_read_project(client):  # topic "cicak" → title "cicak", language id-ID
def test_categories_and_formats_listed(client):  # 5 kategori, 3 format, health fact_check strict
def test_generate_ideas_dedupes_active_job(client):  # POST dua kali → job sama, created true lalu false
def test_list_ideas_empty_then_after_job(client):  # sebelum job: []
def test_select_idea_sets_project(client):  # buat ide manual di DB → select → selected_idea_id + title berubah
def test_providers_list_hides_key(client):  # respons tanpa "api_key" selain has_api_key/hint
```

- [ ] **Langkah 2: RED**.

- [ ] **Langkah 3: Implementasi.**

- [ ] **Langkah 4: Hijau** — `pytest tests/ -q`.

- [ ] **Langkah 5: Commit** — `git commit -m "feat(fase-2): API proyek, kategori, format, ide"`

---

### Task 7: UI project + ide, dan verifikasi E2E

**File:**
- Ubah: `frontend/src/App.tsx` (navigasi dua tampilan: Antrean Job / Proyek), `frontend/src/lib/jobs.ts` (tetap)
- Buat: `frontend/src/lib/projects.ts` + `frontend/src/lib/projects.test.ts`, `frontend/src/Projects.tsx`, `frontend/src/ProjectDetail.tsx`
- Ubah: `frontend/src/styles.css` (+ gaya kartu ide, tetap identitas Fase 1)

**Antarmuka:**
- `projects.ts`: tipe `Project`, `Idea`, `Category`, `Format`; fungsi `fetchProjects`, `createProject`, `fetchProject`, `fetchIdeas`, `generateIdeas`, `selectIdea`, `fetchCategories`, `fetchFormats`; `batchLabel(batch) -> "Batch 1"` dan helper murni `groupByBatch(ideas): Map<number, Idea[]>` (dites).
- `Projects.tsx`: form buat project (topik teks, select kategori, select format — semua opsional kecuali topik/kategori salah satu; pesan error dari API tampil), daftar project (judul, topik, kategori, jumlah ide, lencana "Ide dipilih" bila ada).
- `ProjectDetail.tsx`: info project; tombol "Buat 8 ide" (atau "Buat batch baru") → POST generate → polling project jobs? Polling ide tiap 1 dtk selama ada job ideas aktif (cek lewat daftar job global yang difilter project — Fase 1 `GET /api/jobs` belum memfilter project; pakai `GET /api/projects/{id}/ideas` polling dan status batch muncul bila sudah 8 — plus tampilkan status job dari respons generate). Kartu ide per batch: nomor, judul, hook (kutipan), angle, why_it_works, lencana risiko fakta "Perlu dicek" + fact_note bila `check`, tombol "Pilih ide ini" (atau lencana "Terpilih").
- `App.tsx`: tab sederhana dua tombol ("Proyek", "Antrean Job"), state tampilan + project terpilih; tanpa react-router.
- Antislop tetap berlaku: identitas Fase 1 dipakai ulang; kartu ide = permukaan paper dengan border tinta; tidak ada gradasi/glass/emoji dekoratif; teks UI Indonesia; status tidak hanya warna (ada label teks).

- [ ] **Langkah 1: Tes helper** — `groupByBatch` mengelompokkan dan mengurutkan; `batchLabel`. Jalankan `pnpm vitest run` → RED (modul belum ada).
- [ ] **Langkah 2: Implementasi** semua file di atas.
- [ ] **Langkah 3: Hijau lokal** — `pnpm vitest run` lulus, `pnpm build` exit 0.
- [ ] **Langkah 4: E2E nyata (bukti kriteria Fase 2)**
  1. Migrasi DB dev: `cd backend && .venv/bin/alembic upgrade head`.
  2. Jalankan API + worker + web (seperti Fase 1), buat project lewat API dengan topik "kenapa cicak bisa menempel di dinding" kategori kosong.
  3. `POST /projects/{id}/ideas/generate` → tunggu job `completed` → `GET /projects/{id}/ideas` memuat tepat 8 ide batch 1, salah satu berjudul memuat kata cicak, project `category_source = suggested` bila fixture menyarankan slug sah.
  4. `POST /ideas/{id}/select` pada ide pertama → project `selected_idea_id` terisi, `title` = judul ide.
  5. Halaman web `:5180` memuat daftar project; halaman project menampilkan 8 kartu ide (cek HTML/JS terlayani + API lewat proxy).
  6. Matikan semua server.
- [ ] **Langkah 5: Suite penuh segar** — backend `pytest` semua + `ruff check app tests`; frontend `vitest run` + `build`.
- [ ] **Langkah 6: Commit** — `git commit -m "feat(fase-2): UI proyek dan ide + e2e dry-run"`

## Setelah semua task

- Bangun paket review dari diff terhadap ujung Fase 1, kirim ke reviewer subagent fresh beserta file rencana ini dan focus review di bawah. Perbaiki temuan Critical/Important dalam satu pass TDD; temuan Minor dicatat di ledger `.superpowers/sdd/fase-2-domain-ide/progress.md` sebagai deferred.
- Perbarui `~/MEMORY.md` dan ledger SDD.

## Focus review (pemilik kegagalan yang harus dicek tes)

1. Project tanpa topic dan tanpa kategori tidak bisa lahir — dari API (422 Indonesia) maupun langsung ke DB (check constraint).
2. Sinkronisasi prompt idempoten: menjalankan dua kali tidak membuat versi duplikat; mengedit file kategori memperbarui versi aktif builtin dan aturan yang dirender.
3. Jawaban LLM rusak → satu retry dengan pesan error spesifik; tetap rusak → pindah provider; semua rusak → job gagal `MalformedOutputError`, BUKAN batch setengah jadi (penulisan batch atomik dalam satu transaksi).
4. Handler `ideas` yang diulang untuk job yang sama tidak membuat batch kedua dan tidak memanggil LLM lagi (job_id).
5. API key provider tidak pernah muncul di respons API mana pun (termasuk error dan adapters).
6. Generate ide dua kali saat job masih aktif → satu job, `created=false` pada panggilan kedua; tidak ada batch ganda.
7. Aturan ide ditegakkan oleh kode, bukan dipercaya dari LLM: tepat 8, judul 20–90, kemiripan < 0,8, `fact_risk/note` konsisten, slug saran tidak sah → null.
