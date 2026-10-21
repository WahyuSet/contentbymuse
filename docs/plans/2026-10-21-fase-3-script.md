# Fase 3 — Script, Cek, Validasi, Revisi, Editor: Rencana Implementasi

> **Untuk agen pelaksana:** Wajib memakai sub-skill: gunakan superpowers:subagent-driven-development (disarankan) atau superpowers:executing-plans untuk menjalankan rencana ini per task. Langkah memakai kotak centang (`- [ ]`) untuk pelacakan. Gaya UI mengikuti antislop (identitas Fase 1-2) dan komentar kode mengikuti antislop-code.

**Tujuan:** Ide terpilih menjadi script berversi yang lolos cek otomatis, divalidasi LLM dengan loop revisi terbatas, bisa diedit per scene oleh pemilik, dan disetujui di Gerbang B (`active_script_id` terisi).

**Arsitektur:** Model `script`/`scene`/`validation_result`/`app_setting` + `project.active_script_id` (migrasi 0003). `run_checks` adalah fungsi murni atas daftar scene. Rantai job linear (§4.12): `script` → (cek error? `checks_fix`) → `validate` → (NEEDS_REVISION & revisi tersisa? `revise` → cek → `validate`) → `finalize_best` memilih versi terbaik sebagai aktif. Semua pengantrean rantai memakai `enqueue_once` agar idempoten sesudah worker mati. Handler menulis versi script yang dicatat `job_id`-nya; retry memakai versi itu.

**Stack teknologi:** yang sudah ada (FastAPI, SQLAlchemy async, Alembic, Pydantic, React + TanStack Query). Tidak ada dependensi baru.

## Konteks dari Spec (mengikat)

- Baris Fase 3 di §14: "Script, cek otomatis, validasi, revisi, editor scene. Selesai bila: Script tervalidasi bisa diedit dan disetujui."
- §2.1 `script`: `id, project_id (fk), idea_id (fk null), version (unik per project), parent_id (fk null), source (generated/revised/fixed), schema_version, title, hook, estimated_duration_s (dihitung kode), claims_to_verify (JSON), status (draft/validated/needs_attention/approved), edited_after_validation (bool), best_score (int null), prompt_version_id, job_id, created_at, updated_at`. `job_id` = idempotensi versi.
- §2.1 `scene` (kolom Fase 3): `id, script_id (fk), position (unik per script), beat (hook/setup/main/payoff/cta/loop), voiceover, subtitle_override (null), visual_prompt, include_mascot, visual_type (character/object/process/environment/diagram/closeup), transition (cut/crossfade/punch_in, default cut), emphasis_words (JSON), est_duration_s, revision`. Kolom `transition_sfx`/`event_sfx`/`event_word` datang Fase 6c (migrasi 0009) — JANGAN dibuat sekarang.
- §2.1 `validation_result`: `id, script_id, attempt, status (PASS/NEEDS_REVISION/FAIL), score 0..100, issues (JSON), claims_to_verify, summary, prompt_version_id, job_id, created_at`.
- §2.1 catatan: `active_script_id` ditambah migrasi Fase 3. `app_setting` (§2.3): `key` (PK), `value` (JSON).
- §3.2 `ScriptDraft` (`script.v1`): field contoh spec; aturan: scene 8–14; `voiceover` 3–16 kata; `hook` selalu sama dengan narasi scene 1 — kode menyalinnya setiap kali script disimpan/diedit; normalizer menerima tag `[NO_MASCOT]` di awal `visual_prompt` (hapus, `include_mascot=false`); `visual_prompt` Inggris, voiceover Indonesia; field `start_time`/`end_time`/`duration` TIDAK diminta dari LLM.
- §3.3 `ValidationOutput` (`validation.v1`): `status, score, summary, issues[{severity error/warning/suggestion, area, scene_position, message, suggestion, needs_change}], claims_to_verify`. Aturan bisnis dasar: `PASS` tidak boleh disertai issue `error` → turunkan ke `NEEDS_REVISION`. (Penyaringan `needs_change` Fase 6e dan bukti kutipan 6o di luar lingkup fase ini — lihat Keputusan 3.)
- §4.2 rantai script: render prompt → StructuredLLM → simpan versi `generated` + scene, hitung `est_duration_s` → cek otomatis → ada error: satu kali `script.fix` → versi `fixed` → cek lagi → enqueue `validate`.
- §4.3 `run_checks(scenes, wps, rules)`: 15 kode (`scene_count, duration_range, hook_length, scene_too_long, scene_too_short, visual_repeat, mascot_ratio, empty_field, duplicate_voiceover, tts_risk, beat_order, loop_dangling, written_register, repeated_opener, numbered_points`) dengan severity sesuai tabel spec. Estimasi: `kata / wps + 0,15` per scene. `wps` dari kalibrasi suara project; belum ada sampel → 2,3.
- §4.4 loop validasi: PASS → `validated`; NEEDS_REVISION → revisi < `max_revisions` (bawaan 2, per project di `settings.max_revisions`): `revise` → versi baru → cek (→ `checks_fix` bila error; versi `fixed` tidak dihitung revisi) → `validate` lagi; habis → `needs_attention`. FAIL → `needs_attention`. Validator menerima hasil cek + payload per scene (`words`, `est_seconds`, `total_words`, `estimated_total_s`). Validasi manual (`auto_revise: false`) tidak pernah merevisi dan tidak memindahkan `active_script_id`. **Versi terbaik** (`finalize_best`, saat loop berhenti): versi tanpa error cek → validasi terakhirnya tanpa issue `error` → `best_score` tertinggi → terbaru. Provider validasi bisa diatur terpisah (`app_setting.validation_provider_id`), bawaan: kandidat LLM prioritas tertinggi.
- §4.5 Gerbang B & editor: `PATCH /scenes/{id}` menaikkan `revision`, cek ulang sinkron, `edited_after_validation = true` bila script sudah divalidasi. Tambah/hapus/urutkan menormalisasi `position`. Edit hanya untuk versi aktif dan tanpa job rantai script aktif (`script`, `checks_fix`, `validate`, `revise`) → selain itu 409 `ScriptBusy` atau `ScriptNotActive`. Daftar klaim tampil = klaim script + klaim validasi terakhir, kemiripan token ≥ 0,7 dianggap satu (rumusan belakangan menggantikan di posisinya). `POST /scripts/{id}/approve` butuh `claims_confirmed` (422 `ClaimsNotConfirmed`) dan tidak ada scene kosong (409 `EmptyScene`); hasilnya `approved` + `active_script_id`; hanya satu `approved` per project — yang lama kembali ke status validasi terakhirnya.
- §4.12 reconcile: cabang Gerbang A meng-enqueue `script` bila ide terpilih belum punya script — **kewajiban dari review Fase 2**: cek keberadaan script untuk ide itu wajib ditambahkan sekarang karena handler `script` mendarat di fase ini.
- §6.1 prompt baru: `tasks/script.generate/v1.md`, `tasks/script.fix/v1.md`, `tasks/script.revise/v1.md`, `tasks/validate.script/v1.md`; blok `blocks/pacing.md`, `blocks/visual_rules.md`, `blocks/mascot.md`, `blocks/spoken_indonesian.md`, `blocks/hook_rules.md` (dipakai prompt ide & script, §4.4 catatan hook). Blok yang sudah ada (`output_rules`) tetap.
- §9 rute Fase 3: `GET /projects/{id}/scripts`, `GET /scripts/{id}` (script + scene + hasil cek + validasi terakhir + klaim gabungan), `POST /scripts/{id}/validate`, `POST /projects/{id}/script/generate`, `POST /scripts/{id}/approve`, `POST /scripts/{id}/scenes`, `PATCH /scenes/{id}`, `DELETE /scenes/{id}`, `POST /scripts/{id}/scenes/reorder`. Plus `GET /projects/{id}/pipeline` HANYA tahap `script` + `validation` (§4.13) — tahap lain lahir di fase masing-masing; fase ini mengembalikan kedua tahap itu saja (keputusan dicatat di ledger bila reviewer menilai lain).

## Keputusan lingkup fase ini

1. **Tanpa SFX.** Scene dan ScriptDraft fase ini tidak mengenal `transition_sfx`/`event_sfx`/`event_word` (Fase 6c, migrasi 0009, prompt script v2). Aturan cek yang menyebut SFX tidak ada di §4.3 dasar, jadi tidak terpengaruh.
2. **Tanpa `settings.ending`/loop khusus 6i.** Beat `loop` tetap nilai enum sah; `beat_order` memeriksa hook pertama dan penutup (`cta`/`loop`) terakhir; `loop_dangling` berlaku generik untuk scene `loop` terakhir yang berakhir tanda titik/seru/tanya.
3. **`needs_change` disimpan, tidak disaring.** Field `needs_change` ada di schema (wajib dari model, bawaan True) dan tersimpan di `issues`, tetapi penyaringan 6e (buang issue `needs_change=false`, dedup, turunkan severity tanpa suggestion, naikkan status) TIDAK diterapkan di fase ini; hanya aturan dasar §3.3 (PASS + error → NEEDS_REVISION).
4. **`wps` selalu 2,3 di fase ini.** Tabel `voice_calibration` dan pin suara lahir Fase 4; `run_checks` menerima `wps` sebagai parameter agar Fase 4 tinggal mengisi sumbernya.
5. **FakeLLM fixture script & validasi.** Fixture script: 10 scene lolos cek tanpa error untuk topik dari ide (judul/hook dari ide terpilih), `claims_to_verify` 2 butir. Fixture validasi: `PASS`, skor 85, tanpa issue error. Kriteria fase ("script tervalidasi bisa diedit dan disetujui") terbukti ujung-ke-ujung dalam dry-run; LLM sungguhan memakai jalur yang sama.
6. **`enqueue_once` di `app/jobs/queue.py`**: mencari job aktif ATAU job terakhir (status apa pun) dengan `(type, project_id, scene_id, input_hash)` yang sama persis; bila ada kembalikan job itu (`created=False`), selain itu enqueue baru. Rantai memakai input kanonis kecil (`{"script_id": …}` / `{"idea_id": …}`) agar hash stabil. Berbeda dari unique index aktif: `enqueue_once` juga menelan job yang sudah selesai/gagal (untuk rantai linear yang tidak boleh diulang), sesuai pemakaian §4.4/§4.10.

## Konvensi global

- Warisan Fase 1-2 berlaku: ULID, UTC, `/api`, error standar, pesan Indonesia, TDD, commit per task, ruff bersih, tidak ada komentar dekoratif (antislop-code).
- Migrasi baru `0003` setelah `0002`. Branch `feat/fase-3-script` dari ujung Fase 2.
- `HANDLERS` bertambah: `script`, `checks_fix`, `validate`, `revise`. `POST /api/jobs` tetap hanya `provider_test` (rantai dibuat lewat endpoint project/reconcile).

---

### Task 1: Model script/scene/validasi + migrasi 0003 + schema LLM

**File:**
- Ubah: `backend/app/db/models.py` (+ `Script`, `Scene`, `ValidationResult`, `AppSetting`; `Project.active_script_id`)
- Buat: `backend/alembic/versions/0003_script.py`
- Ubah: `backend/app/domain/llm_outputs.py` (+ `ScriptDraft`, `SceneDraft`, `ValidationOutput`, `ValidationIssue`; registry `OUTPUT_MODELS`)
- Buat: `backend/tests/test_script_models.py`

**Antarmuka:**
- `Script` persis §2.1 (kolom Fase 3); `UniqueConstraint(project_id, version)`; `status` default `draft`; `edited_after_validation` default False; `schema_version` default `script.v1`; `claims_to_verify` JSON default list.
- `Scene` persis kolom Fase 3; `UniqueConstraint(script_id, position)`; `revision` default 0... spec: "naik setiap kali diedit" — default 1? Tetapkan default 0, PATCH menaikkan menjadi 1, 2, … (dicatat di sini agar konsisten). `emphasis_words` JSON default list; `transition` default `cut`.
- `ValidationResult` persis §2.1; `issues` JSON default list.
- `AppSetting`: `key` PK String(64), `value` JSON. Helper `async def get_setting(session, key, default=None)` dan `set_setting` di `backend/app/services/settings.py`.
- `ScriptDraft`: `schema_version: str = "script.v1"`, `title`, `hook`, `scenes: list[SceneDraft]`, `claims_to_verify: list[str]`. `SceneDraft`: `beat` (pattern enum), `voiceover` (kata 3–16 ditegakkan validator bisnis, bukan Pydantic — sama seperti ide: supaya pesan retry spesifik), `subtitle: str | None`, `visual_prompt`, `include_mascot: bool = True`, `visual_type` (pattern enum), `transition` (pattern, default `cut`), `emphasis_words: list[str] = []`.
- `validate_script_draft(draft) -> ScriptDraft` di `structured_llm.py` atau modul domain baru `app/domain/script_rules.py` (pilih: `script_rules.py`, Task 2 menaruh `run_checks` di sana juga): scene 8–14 (ValueError menyebut jumlah); per scene kata voiceover 3–16; normalisasi `[NO_MASCOT]`; `hook` disalin dari voiceover scene 1.
- `ValidationOutput`: `status` pattern `PASS|NEEDS_REVISION|FAIL`, `score` 0..100, `summary`, `issues: list[ValidationIssue]`, `claims_to_verify`. `ValidationIssue`: `severity` pattern, `area`, `scene_position: int | None`, `message`, `suggestion: str | None = None`, `needs_change: bool = True`.
- `apply_validation_rules(output) -> ValidationOutput`: PASS + ada issue severity error → status NEEDS_REVISION.

- [ ] **Langkah 1: Tes** — model tersimpan & constraint unik versi; `active_script_id` bisa diisi; `validate_script_draft` menolak 7 scene, menerima 10, menyalin hook, menangani `[NO_MASCOT]`; `apply_validation_rules` menurunkan PASS ber-error.
- [ ] **Langkah 2: RED** — import gagal.
- [ ] **Langkah 3: Implementasi** model + migrasi (termasuk `ALTER project ADD active_script_id`, tabel `app_setting`) + schema.
- [ ] **Langkah 4: Hijau** — suite penuh + `alembic upgrade head` di DB sementara memuat 14 tabel.
- [ ] **Langkah 5: Commit** — `feat(fase-3): model script, scene, hasil validasi`

### Task 2: `run_checks` murni + estimasi durasi

**File:**
- Buat: `backend/app/domain/script_rules.py` (atau lanjutkan dari Task 1 bila sudah dibuat)
- Buat: `backend/tests/test_checks.py`

**Antarmuka:**
- `@dataclass CheckIssue: code: str; severity: str; scene_position: int | None; message: str` (pesan Indonesia; `duration_range` menyebut jumlah kata + kira-kira kata yang perlu dipangkas/ditambah; `hook_length` menyebut kata hook + batasnya).
- `@dataclass SceneLike` — fungsi menerima list dict ATAU objek scene ORM: normalisasi internal membaca atribut/kunci `voiceover, visual_prompt, visual_type, beat, include_mascot` + `position`.
- `estimate_scene_s(voiceover: str, wps: float) -> float` = `len(words)/wps + 0.15`; `count_words(text)`.
- `run_checks(scenes, *, wps: float = 2.3, target_min_s: int = 30, target_max_s: int = 40, format_slug: str | None = None) -> list[CheckIssue]` mengimplementasikan 15 kode §4.3 persis ambang tabelnya:
  - `scene_count` error di luar 8..14; `duration_range` error di luar target (memakai total estimasi); `hook_length` error estimasi scene 1 > 3,5 dtk; `scene_too_long` warning > 12 kata atau estimasi > 5 dtk; `scene_too_short` warning < 3 kata; `visual_repeat` warning visual_type sama > 2 berturut-turut; `mascot_ratio` warning maskot di semua scene ATAU tidak ada maskot di scene hook; `empty_field` error voiceover/visual_prompt kosong; `duplicate_voiceover` error identik atau sangat mirip (rasio token ≥ 0,9); `tts_risk` warning simbol `% & /`, angka romawi (regex token `\b[IVXLCDM]{2,}\b`), singkatan kapital ≥ 3 huruf semua kapital, atau URL; `beat_order` warning hook bukan pertama / cta|loop bukan terakhir; `loop_dangling` warning scene loop terakhir berakhir `.`/`!`/`?`; `written_register` warning kata: adalah, bahwa, merupakan, tersebut, tak, yaitu, dimana; `repeated_opener` warning dua scene berurutan awalan kata sama atau "jadi" membuka > 1 scene; `numbered_points` warning bila `format_slug == "top-list"` dan tidak ada awalan "Pertama," "Kedua," "Ketiga," berurutan di scene mana pun.

- [ ] **Langkah 1: Tes per aturan** — satu fungsi tes per kode (positif + negatif kunci): script contoh 10 scene bersih → nol error (warning boleh, tapi contoh dibuat nol issue); mutasi terarah memicu kode yang diharapkan.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau** — suite penuh.
- [ ] **Langkah 5: Commit** — `feat(fase-3): cek otomatis script (run_checks)`

### Task 3: Prompt script/validasi + blok + fixture FakeLLM

**File:**
- Buat: `backend/app/prompts/tasks/script.generate/v1.md`, `script.fix/v1.md`, `script.revise/v1.md`, `validate.script/v1.md`
- Buat: `backend/app/prompts/blocks/{pacing,visual_rules,mascot,spoken_indonesian,hook_rules}.md`
- Ubah: `backend/app/prompts/tasks/ideas.from_topic/v1.md` + `ideas.discover/v1.md` (sisipkan `{% include "blocks/hook_rules.md" %}` — edit file menaikkan versi DB otomatis, mekanisme Fase 2)
- Ubah: `backend/app/providers/llm/fake.py` (+ fixture script & validasi)
- Ubah: `backend/tests/test_prompts.py` (+ render script.generate memuat blok pacing & kontrak), `backend/tests/test_structured_llm.py` atau file baru `test_fake_fixtures.py`

**Antarmuka:**
- Frontmatter: `script.generate` inputs `[idea, category, format, pacing, language, target_min_s, target_max_s]`, output `ScriptDraft`, temperature 0,8, max_tokens 6000. `script.fix` inputs `[draft, issues, …sama]`, output `ScriptDraft`. `script.revise` inputs `[draft, validation, checks, …]`, output `ScriptDraft`. `validate.script` inputs `[script, checks]`, output `ValidationOutput`, temperature 0,3, max_tokens 4000.
- Isi prompt: instruksi Inggris, contoh Indonesia (§6.1); blok pacing memuat angka target (30–40 dtk, 8–14 scene, hook ≤ 3,5 dtk, 3–16 kata/scene) sebagai teks yang dirender dengan variabel target dari inputs bila ada.
- FakeLLM deteksi: kontrak memuat `"schema_version"` → fixture script; kontrak memuat `"score"` dan `"summary"` tanpa `schema_version` → fixture validasi PASS 85. Fixture script dibangun dari baris `Judul ide: …` yang akan ditulis prompt `script.generate` (baris `Idea title: {{ idea.title }}` — pakai penanda Inggris konsisten: `Idea title:`), 10 scene: beats hook, setup, main×6, payoff, cta; voiceover 6–8 kata (hook 6 kata), total kata ≈ 74 → estimasi ≈ 74/2,3 + 1,5 ≈ 33,7 dtk (di dalam 30–40); visual_type berganti agar tidak > 2 berurutan; maskot tidak di semua scene (scene 4 dan 8 false) dan ada di hook; tanpa kata register tertulis, tanpa simbol tts_risk; `claims_to_verify` 2 butir generik dari judul ide.

- [ ] **Langkah 1: Tes** — render `script.generate` berisi blok pacing + `ScriptDraft` sebagai output_model; fixture FakeLLM script lolos `validate_script_draft` DAN `run_checks` tanpa error; fixture validasi lolos model.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi** prompt + fixture.
- [ ] **Langkah 4: Hijau**.
- [ ] **Langkah 5: Commit** — `feat(fase-3): prompt script & validasi, fixture FakeLLM`

### Task 4: `enqueue_once` + handler `script` & `checks_fix`

**File:**
- Ubah: `backend/app/jobs/queue.py` (+ `enqueue_once`)
- Buat: `backend/app/jobs/script_chain.py` (helper bersama: muat konteks project/ide/kategori/format, simpan draft sebagai versi script, `queue_checks_or_validate`)
- Buat: `backend/app/jobs/script.py` (handler script), `backend/app/jobs/checks_fix.py`
- Ubah: `backend/app/jobs/handlers.py` (daftar keduanya)
- Buat: `backend/tests/test_script_job.py`

**Antarmuka:**
- `async def enqueue_once(session, *, type, input, project_id=None, scene_id=None) -> tuple[GenerationJob, bool]` — cari job dengan `(type, project_id, scene_id, input_hash)` sama dalam status APA PUN (terbaru dulu); ketemu → `(job, False)`; tidak → enqueue + `(job, True)`. Tangkap IntegrityError dari index aktif → muat ulang job aktif yang menang, `created=False`.
- `async def save_draft(session, *, project, idea_id, draft: ScriptDraft, source, parent_id, job, prompt_version_id) -> Script` — version = max+1 per project; tulis Script + Scene (est per scene wps 2,3), `estimated_duration_s` total, `status="draft"`, `job_id=job.id`.
- `async def queue_checks_or_validate(session, *, script, job, after_fix: bool = False) -> GenerationJob` — jalankan `run_checks` atas scene script; ada error dan tidak `after_fix` → `enqueue_once(type="checks_fix", input={"script_id": id}, project_id)`; selain itu `enqueue_once(type="validate", input={"script_id": id, "auto_revise": True}, project_id)`.
- Handler `script` (input `{"idea_id"}`): versi dengan `job_id == job.id` sudah ada → pakai versi itu (idempotensi §2.1), lanjut `queue_checks_or_validate`; belum → render `script.generate` (idea dict: title/angle/hook dari ContentIdea; category/format dict seperti handler ideas; language; target) → StructuredLLM + `validate_script_draft` → `save_draft(source="generated")` → usage_record → `queue_checks_or_validate`. Tanpa ide terpilih/project → error `LookupError` retryable False? Pakai pola `NoLlmProviderError`: kelas `ScriptInputError(kind="ScriptInputMissing", retryable=False)` pesan Indonesia.
- Handler `checks_fix` (input `{"script_id"}`): versi `fixed` dengan `job_id == job.id` sudah ada → lanjut antre validate untuk versi itu; belum → muat script + issues cek error saja → prompt `script.fix` → simpan versi `source="fixed"`, `parent_id` script asal → usage → `enqueue_once validate` untuk versi fixed.

- [ ] **Langkah 1: Tes** — rantai kering: project + ide terpilih + provider fake → jalankan worker `run_once` berulang sampai tidak ada job antre: script v1 `generated` tersimpan 10 scene; job `validate` terantre (handler validate belum ada di task ini → daftarkan stub? TIDAK: tes berhenti pada keadaan sesudah handler script: assert job validate `queued` ada lewat `enqueue_once`; handler checks_fix diuji terpisah dengan draft rusak yang dibuat manual (scene 5) → versi fixed 10 scene). `enqueue_once` satuan: dua kali input sama → created True lalu False, termasuk sesudah job pertama `completed`.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau**.
- [ ] **Langkah 5: Commit** — `feat(fase-3): job script dan checks_fix`

### Task 5: Handler `validate` & `revise`, `finalize_best`, reconcile

**File:**
- Buat: `backend/app/jobs/validate.py`, `backend/app/jobs/revise.py`, `backend/app/services/finalize.py`
- Ubah: `backend/app/jobs/handlers.py`, `backend/app/services/reconcile.py` (cek script-ada), `backend/app/services/settings.py` (dari Task 1 bila belum)
- Buat: `backend/tests/test_validate_chain.py`

**Antarmuka:**
- `build_validation_candidates(session, settings)`: baca `app_setting.validation_provider_id`; bila terisi dan provider itu enabled → kandidat tunggal itu di depan + rantai router biasa sesudahnya; bawaan: `ProviderRouter.candidates("llm")` penuh.
- Handler `validate` (input `{"script_id", "auto_revise": bool}`): hasil dengan `job_id == job.id` sudah ada → jangan panggil LLM lagi; terapkan ulang keputusan status dari hasil itu (idempotensi). Belum → payload validator: script dict (title, hook, scenes + words + est_seconds, total_words, estimated_total_s) dirender ke prompt `validate.script` lewat inputs `script` (JSON string) + `checks` (JSON string issues) → StructuredLLM `ValidationOutput` → `apply_validation_rules` → simpan `ValidationResult(attempt = jumlah hasil untuk script ini + 1, job_id)` → `script.best_score = score` → keputusan:
  - PASS → `script.status = validated`; bila `auto_revise` → `finalize_best(project)`.
  - NEEDS_REVISION → bila `auto_revise` dan jumlah versi `revised` untuk ide ini < max_revisions → `enqueue_once(type="revise", input={"script_id": id, "validation_id": id hasil})`; selain itu `status = needs_attention` + `finalize_best` bila auto_revise.
  - FAIL → `needs_attention` + finalize bila auto_revise.
  - Manual (`auto_revise` False): hanya status PASS→validated / selainnya needs_attention TIDAK — manual: status mengikuti hasil (PASS → validated; NEEDS_REVISION/FAIL → needs_attention) tanpa finalize dan tanpa revise (§4.4).
- Handler `revise` (input `{"script_id", "validation_id"}`): versi `revised` dengan `job_id == job.id` sudah ada → antrekan kelanjutannya saja; belum → prompt `script.revise` (draft JSON + issues validasi + checks) → simpan versi `source="revised"`, parent = script asal → `queue_checks_or_validate`.
- `finalize_best(session, project)`: kandidat = semua script project untuk `selected_idea_id`; skor urut: (punya error cek, validasi terakhir punya issue error, -best_score, -version) → pilih pertama; set `project.active_script_id`. "Validasi terakhir punya issue error" dari `ValidationResult` terbaru script itu; tanpa hasil validasi dianggap punya error (di bawah yang tervalidasi bersih).
- `reconcile`: cabang Gerbang A sekarang memeriksa `Script` dengan `idea_id == selected_idea_id` — hanya enqueue bila belum ada (menutup utang review Fase 2).

- [ ] **Langkah 1: Tes rantai penuh (fake)** — dari ide terpilih: dorong worker sampai rantai berhenti → ada script `validated`, `active_script_id` terisi versi itu, `validation_result` attempt 1 PASS. Tes revisi: ganti fixture validasi? Fixture selalu PASS — untuk jalur revisi, uji handler validate langsung dengan StubLLM NEEDS_REVISION dua kali lalu PASS (pola Task 4 Fase 2) dan `max_revisions=1` di settings project → berakhir `needs_attention` + active terisi versi terbaik. Tes reconcile: panggil dua kali → satu job script.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau**.
- [ ] **Langkah 5: Commit** — `feat(fase-3): validasi, revisi, finalize_best`

### Task 6: API script — baca, generate, validate manual, approve

**File:**
- Buat: `backend/app/api/scripts.py`, daftarkan di `main.py`
- Buat: `backend/tests/test_scripts_api.py`

**Antarmuka:**
- `ScriptSummaryOut(id, project_id, idea_id, version, source, status, title, estimated_duration_s, best_score, edited_after_validation, created_at)`.
- `GET /projects/{id}/scripts` — semua versi urut version desc + ringkasan skor terakhir.
- `GET /scripts/{id}` → `ScriptDetailOut`: script + `scenes: [SceneOut]` (semua kolom Fase 3 + revision) + `checks: [CheckIssueOut]` (run_checks atas scene tersimpan) + `validation`: hasil terakhir atau null + `claims`: klaim gabungan §4.5 (script.claims + validation.claims, dedup token ≥ 0,7, rumusan validasi menggantikan posisi klaim lama yang sama).
- `POST /projects/{id}/script/generate` (202): ide terpilih belum ada → 422 `NoIdeaSelected` ("Pilih ide dulu sebelum membuat script."); job `script` aktif untuk ide itu → kembalikan `created=false`; selain itu enqueue biasa (bukan once — generate manual selalu versi baru) `input={"idea_id": selected}`.
- `POST /scripts/{id}/validate` (202): body `{auto_revise: bool = false}`; enqueue_once validate dengan input itu; kembalikan job + created.
- `POST /scripts/{id}/approve`: body `{claims_confirmed: bool}`; false → 422 `ClaimsNotConfirmed` ("Semua klaim harus dicek dulu sebelum menyetujui."); scene dengan voiceover/visual_prompt kosong → 409 `EmptyScene`; script lain yang `approved` di project sama → kembalikan ke status validasi terakhirnya (PASS→validated, selainnya needs_attention; tanpa hasil → draft); script ini → `approved`, `project.active_script_id = id`; panggil reconcile.

- [ ] **Langkah 1: Tes API** — alur: buat data script manual di DB → GET detail memuat scene + checks + klaim gabungan; approve tanpa konfirmasi → 422; dengan scene kosong → 409; sukses → approved + active berpindah + script approved lama turun status; generate tanpa ide → 422; validate manual membuat job `auto_revise=false`.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau**.
- [ ] **Langkah 5: Commit** — `feat(fase-3): API script dan Gerbang B`

### Task 7: API editor scene

**File:**
- Lanjut `backend/app/api/scripts.py` (rute scene), `backend/tests/test_scenes_api.py`

**Antarmuka:**
- Penjaga edit `assert_script_editable(session, script)`: `project.active_script_id == script.id` selain itu 409 `ScriptNotActive` ("Hanya versi script aktif yang bisa diedit."); ada job aktif tipe rantai script untuk project → 409 `ScriptBusy` ("Tunggu job script selesai dulu sebelum mengedit.").
- `PATCH /scenes/{id}`: body subset `{voiceover, subtitle_override, visual_prompt, include_mascot, visual_type, transition, beat, emphasis_words}`; validasi enum → 422 `InvalidScene` pesan per field Indonesia; terapkan; `revision += 1`; bila status script `validated`/`approved` → `edited_after_validation = true`; hitung ulang `est_duration_s` scene + `estimated_duration_s` script + `hook` (salin dari scene 1) (§3.2); kembalikan SceneOut + checks terbaru script.
- `POST /scripts/{id}/scenes` (201): body scene lengkap (bawaan: beat `main`, transition `cut`, include_mascot true); posisi = sesudah `after_position` (bawaan: akhir); geser posisi lain; normalisasi 1..n.
- `DELETE /scenes/{id}`: hapus + normalisasi posisi + hitung ulang durasi/hook.
- `POST /scripts/{id}/scenes/reorder`: body `{scene_ids: [...]}` harus memuat tepat semua scene script (422 `InvalidSceneOrder`); terapkan urutan; normalisasi; hitung ulang.

- [ ] **Langkah 1: Tes** — PATCH menaikkan revision + edited_after_validation pada script validated; PATCH pada script bukan aktif → 409 ScriptNotActive; saat job validate aktif → 409 ScriptBusy; tambah/hapus/reorder menormalisasi posisi dan hook mengikuti scene 1 baru; enum ngawur → 422.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau**.
- [ ] **Langkah 5: Commit** — `feat(fase-3): editor scene`

### Task 8: UI naskah (antislop)

**File:**
- Buat: `frontend/src/lib/scripts.ts` + `scripts.test.ts` (helper murni: `mergeClaimsPreview`? klaim gabungan dihitung server — helper UI: `statusScriptLabel` memetakan status script ke Indonesia, `formatDuration`)
- Buat: `frontend/src/ScriptPanel.tsx`; ubah `frontend/src/ProjectDetail.tsx` (tambah panel naskah di bawah ide), `frontend/src/styles.css`

**Antarmuka & rancangan (antislop-ui, meneruskan identitas Fase 1-2):**
- Panel "Naskah": daftar versi (nomor, sumber, status berlabel teks, skor) — versi aktif ditandai lencana; tombol "Buat script dari ide terpilih" (atau "Buat versi baru") dengan keadaan menonaktifkan saat job rantai aktif (polling jobs seperti panel ide).
- Tampilan versi aktif/terpilih: judul, hook, total durasi estimasi; daftar scene sebagai baris editor: nomor, beat (select), voiceover (textarea), prompt visual (input), maskot (checkbox), durasi estimasi; tombol simpan per scene (PATCH), hapus, naik/turun (reorder), tambah scene. Tidak ada drag-and-drop, tidak ada kartu melayang/gradasi — tabel/baris kertas berbatas tinta seperti halaman job.
- Panel cek: daftar issue dengan label severity teks ("Kesalahan"/"Peringatan") + pesan; kosong → teks "Tidak ada masalah cek otomatis."
- Panel validasi: status + skor + ringkasan + issue; tombol "Validasi ulang" (manual).
- Gerbang B: daftar klaim dengan checkbox per klaim; tombol "Setujui script" aktif hanya bila semua klaim tercentang; error server tampil apa adanya.
- Semua teks UI Indonesia; status tidak hanya warna.

- [ ] **Langkah 1: Tes helper** — `statusScriptLabel` (draft→"Draf", validated→"Tervalidasi", needs_attention→"Perlu perhatian", approved→"Disetujui"), `formatDuration(33.7)` → "±34 detik". RED dulu.
- [ ] **Langkah 2: Implementasi.**
- [ ] **Langkah 3: Hijau** — `pnpm vitest run` + `pnpm build`.

### Task 9: E2E + review menyeluruh

- [ ] **Langkah 1: E2E hidup** — server bertiga jalan; project topik cicak → generate ide → pilih ide → (reconcile/worker) script terbuat → rantai sampai `validated` + `active_script_id`; PATCH satu scene lewat API (revision naik, edited_after_validation true); approve dengan klaim terkonfirmasi → status `approved`; UI :5180 melayani halaman project (cek HTML + API proxy). Matikan server.
- [ ] **Langkah 2: Suite segar penuh** — backend pytest + ruff; frontend vitest + build.
- [ ] **Langkah 3: Commit** — `feat(fase-3): UI naskah + e2e script tervalidasi`.
- [ ] **Langkah 4: Review** — paket diff dari ujung Fase 2 → reviewer subagent fresh dengan Focus review di bawah; perbaiki Critical/Important satu pass TDD; Minor ke ledger `.superpowers/sdd/fase-3-script/progress.md`. Perbarui `~/MEMORY.md`.

## Focus review

1. Rantai tidak bisa dobel: dua reconcile/generate bersamaan dan retry worker di tengah rantai tidak menghasilkan dua versi untuk satu job, dua job validate untuk input sama, atau loop revisi tak berujung (max_revisions ditegakkan dari hitungan versi `revised`, bukan dari memori proses).
2. Handler yang diulang sesudah worker mati memakai versi/hasil yang ditulis job itu sendiri (`script.job_id`, `validation_result.job_id`), bukan memanggil LLM lagi.
3. `finalize_best` memilih sesuai urutan §4.4 dan tidak pernah memilih versi ber-error cek bila ada yang bersih.
4. Edit scene terkunci benar: bukan versi aktif → 409 ScriptNotActive; rantai berjalan → 409 ScriptBusy; sesudah edit, durasi + hook selalu konsisten dengan scene tersimpan.
5. Approve menolak klaim belum terkonfirmasi (422) dan scene kosong (409), dan hanya menyisakan satu script `approved` per project.
6. Aturan script ditegakkan kode: jumlah scene, kata per scene, hook = scene 1, `[NO_MASCOT]`, PASS ber-error turun status.
7. Klaim gabungan untuk Gerbang B: dedup token ≥ 0,7 dengan rumusan validasi menggantikan posisi klaim lama.
