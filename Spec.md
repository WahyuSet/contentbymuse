# Spec Teknis: Stickman Content Factory

| | |
|---|---|
| Status | Draf untuk review |
| Tanggal | 2026-10-07 |
| PRD | [../PRD.md](../PRD.md) |

Dokumen ini menjelaskan **bagaimana** sistem dibangun. Apa dan kenapa ada di PRD.

---

## 1. Arsitektur

```text
┌──────────────── Browser (React SPA) ────────────────┐
│ Dashboard · Idea Picker · Script Editor · Pipeline  │
│ Scene Grid · Preview · Metadata · Settings          │
└───────────────┬─────────────────────────────────────┘
                │ REST JSON + polling status
┌───────────────▼─────────────────────────────────────┐
│ API (FastAPI): validasi input, baca/tulis DB,       │
│ membuat job, memanggil reconcile. Tidak memanggil AI│
└───────┬───────────────────────────────┬─────────────┘
        │                               │
┌───────▼──────────┐           ┌────────▼──────────┐
│ Database         │           │ Storage           │
│ SQLite → Postgres│           │ Local → S3/R2     │
│ juga antrean job │           └────────▲──────────┘
└───────▲──────────┘                    │
┌───────┴───────────────────────────────┴──────────┐
│ Worker: pipeline stages → service layer →        │
│ ProviderRouter → adapter → API eksternal         │
│ FFmpeg (subprocess) · faster-whisper             │
└──────────────────────────────────────────────────┘
```

Aturan lapisan:

- `api` hanya memanggil `services` dan `jobs.enqueue`. Tidak ada pemanggilan provider di request HTTP.
- `pipeline` (satu modul per tahap) hanya mengenal interface kemampuan: `generate_text`, `synthesize`, `generate_image`, `Storage`, `VideoRenderer`.
- Nama vendor hanya muncul di `providers/<capability>/<adapter>.py` dan di tabel registry `ADAPTERS`.

### 1.1 Stack

| Lapisan | Pilihan |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, dikelola `uv` |
| Validasi | Pydantic v2, pydantic-settings |
| Database | SQLAlchemy 2 (async), Alembic. SQLite mode WAL di localhost, Postgres di VPS |
| HTTP klien | httpx (async), SDK `openai` untuk endpoint OpenAI-compatible |
| Template | Jinja2 dengan `StrictUndefined` |
| Audio/video | FFmpeg dan ffprobe lewat subprocess, faster-whisper, Pillow |
| Rahasia | `cryptography.fernet` |
| Frontend | React 18, Vite, TypeScript, TanStack Query, React Router, `openapi-typescript` |
| Kualitas | ruff, pyright, pytest, pytest-asyncio, respx · eslint, vitest |

### 1.2 Struktur repo

```text
stickman/
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py            FastAPI app factory
│   │   ├── worker.py          entrypoint: python -m app.worker
│   │   ├── config.py          Settings (pydantic-settings)
│   │   ├── api/               router per resource
│   │   ├── domain/            model Pydantic (schema output LLM, DTO API)
│   │   ├── db/                model SQLAlchemy, session, repository
│   │   ├── pipeline/          ideas, script, checks, validate, revise, voice,
│   │   │                      align, image, render, metadata, thumbnail, export
│   │   ├── services/          structured_llm, prompt_service, usage, hashing, reconcile
│   │   ├── providers/         base.py, registry.py, errors.py, llm/, voice/, image/
│   │   ├── prompts/           tasks/, blocks/, categories/, formats/
│   │   ├── jobs/              queue.py, worker_loop.py, context.py, handlers.py
│   │   ├── render/            models.py, cues.py, plan.py, ffmpeg_builder.py, runner.py, ass.py, srt.py, motion.py
│   │   ├── storage/           base.py, local.py
│   │   └── assets/            fonts/ (tanpa musik bawaan: musik latar diunggah pemilik)
│   └── tests/
├── frontend/
├── docs/
├── storage/                   (gitignore)
└── dev.ps1                    menjalankan api, worker, web
```

### 1.3 Proses

| Proses | Localhost | VPS |
|---|---|---|
| API | `uv run uvicorn app.main:serve --factory --host 127.0.0.1 --port 8010` (lewat `dev.ps1`) | container `api` |
| Worker | `uv run python -m app.worker` | container `worker` |
| Web | `pnpm dev` (Vite di port 5180, proxy `/api` ke 8010) | build statis, disajikan Caddy |
| DB | file SQLite di `storage/app.db` | container Postgres |

---

## 2. Domain model

ID memakai ULID (string 26 karakter, terurut waktu). Semua waktu dalam UTC. Kolom JSON memakai tipe `JSON` SQLAlchemy (TEXT di SQLite, JSONB di Postgres).

### 2.1 Konten

**`category`** dan **`format`**: dibaca dari file `prompts/categories/*.md` dan `prompts/formats/*.md`, disinkronkan ke tabel saat startup.

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | ulid | |
| `slug` | str unik | contoh `animals`, `myth-vs-fact`. Pengenal stabil. |
| `name` | str | nama tampilan berbahasa Indonesia |
| `description` | str | |
| `fact_check` | enum `normal` / `strict` | hanya di `category` |
| `prompt_template_id` | fk | fragmen aturan, berversi seperti prompt lain |
| `enabled` | bool | |

**`project`**

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | ulid | |
| `title` | str | awalnya dari topik, lalu dari ide terpilih |
| `topic` | str null | |
| `category_id` | fk null | pilihan pengguna atau hasil tebakan |
| `category_source` | enum `user` / `suggested` / null | |
| `format_id` | fk null | null berarti Bebas |
| `language` | str | default `id-ID` |
| `target_min_s`, `target_max_s` | int | default 0, 45 (Fase 11: durasi bukan target — video cukup di bawah 45 detik) |
| `selected_idea_id` | fk null | |
| `active_script_id` | fk null | |
| `visual_style_id` | fk | |
| `voice_provider_id`, `voice_id`, `voice_settings` | fk, str, JSON | satu suara untuk seluruh project |
| `image_provider_id` | fk | |
| `video_provider_id` | fk null | provider video untuk proyek dalam mode video (Fase 6s, migrasi 0012) |
| `settings` | JSON | override per project: `auto_render`, `max_revisions`, `bgm`, `sfx` (`{"enabled": bool}`, default menyala, Fase 6c), `visual_mode` (`image` bawaan / `video`, Fase 6s), `allow_image_fallback` |
| `created_at`, `updated_at` | datetime | |

Constraint: `topic` atau `category_id` wajib terisi salah satu. Kolom `active_script_id`, `visual_style_id`, `voice_*`, `image_provider_id`, dan `video_provider_id` ditambah oleh migrasi fase yang memakainya (Fase 3, 4, dan 6s).

**`content_idea`**: `id`, `project_id`, `batch` (int), `position` (1..8), `title`, `angle`, `hook`, `why_it_works`, `suggested_category_slug`, `fact_risk` (`low` / `check`, null untuk ide sebelum Fase 6d), `fact_note` (null kecuali `check`; migrasi 0010), `job_id` (job yang menulis batch ini; retry setelah worker mati memakai batch itu, bukan membuat batch kedua), `created_at`.

**`script`**

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | ulid | |
| `project_id` | fk | |
| `idea_id` | fk null | ide asal; `reconcile` memakainya untuk tahu apakah ide terpilih sudah punya script |
| `version` | int | unik per project |
| `parent_id` | fk null | versi asal untuk revisi |
| `source` | enum `generated` / `revised` / `fixed` | |
| `schema_version` | str | contoh `script.v1` |
| `title`, `hook` | str | |
| `estimated_duration_s` | float | dihitung ulang oleh kode, tidak dari LLM |
| `claims_to_verify` | JSON list[str] | |
| `status` | enum `draft` / `validated` / `needs_attention` / `approved` | |
| `edited_after_validation` | bool | |
| `best_score` | int null | skor validasi terakhir |
| `prompt_version_id`, `job_id` | fk | `job_id` = job yang menulis versi ini; handler yang diulang setelah worker mati memakai versi itu, bukan membuat versi kedua |
| `created_at`, `updated_at` | datetime | |

**`scene`**

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | ulid | stabil selama scene ada |
| `script_id` | fk | |
| `position` | int | 1..n, unik per script |
| `beat` | enum `hook` / `setup` / `main` / `payoff` / `cta` / `loop` | `loop` sejak Fase 6i |
| `voiceover` | str | |
| `subtitle_override` | str null | default: subtitle diturunkan dari voiceover |
| `visual_prompt` | str | tanpa tag di dalam teks |
| `include_mascot` | bool | |
| `visual_type` | enum `character` / `object` / `process` / `environment` / `diagram` / `closeup` | |
| `transition` | enum `cut` / `crossfade` / `punch_in` | default `cut` |
| `emphasis_words` | JSON list[str] | kata yang disorot di subtitle |
| `transition_sfx` | enum `whoosh` / `slorot` null | SFX di potongan masuk ke scene ini; tidak pernah di scene 1 (Fase 6c, migrasi 0009) |
| `event_sfx` | enum `ding` / `pop` / `boom` null | SFX pada satu kata yang diucapkan |
| `event_word` | str null | kata pemicu `event_sfx`; kosong berarti kata pertama scene; ikut terhapus bila `event_sfx` dihapus |
| `est_duration_s` | float | dari jumlah kata dan kecepatan bicara |
| `revision` | int | naik setiap kali diedit |

`asset.scene_id` (CASCADE), `generation_job.scene_id` dan `generation_job.parent_id` (SET NULL) punya foreign key sejak Fase 4 (migrasi 0005).

**`validation_result`**: `id`, `script_id`, `attempt`, `status` (`PASS` / `NEEDS_REVISION` / `FAIL`), `score` (0..100), `issues` (JSON, lihat 4.4), `claims_to_verify`, `summary`, `prompt_version_id`, `job_id`, `created_at`.

**`platform_metadata`**: `id`, `project_id`, `script_id`, `platform` (`youtube_shorts` / `tiktok` / `facebook_reels`), `version`, `title` (null kecuali YouTube), `body` (deskripsi atau caption), `hashtags` (JSON), `tags` (JSON, YouTube), `is_selected`, `edited_by_user`, `job_id`. Fase 6 (migrasi 0007) menambah `input_hash` (hash script saat metadata dibuat, untuk status usang yang dihitung), `prompt_version_id`, `provider_id`, `model`, dan `created_at`. Unik: `(project_id, platform, version)`, `job_id`, dan satu `is_selected` per `(project_id, platform)` (indeks parsial). Versi hasil LLM tidak pernah diubah: edit pertama membuat versi baru `edited_by_user = true` yang terpilih, edit berikutnya pada versi buatan pengguna memperbarui baris itu (lihat 4.10).

**`thumbnail_concept`** (Fase 6b, migrasi 0008): `id`, `project_id` (CASCADE), `script_id` (SET NULL), `version`, `title_text` (teks yang digambar di thumbnail, 2 sampai 40 karakter, satu baris, 2 sampai 6 kata), `visual_prompt` (Inggris, 20 sampai 800 karakter), `include_mascot`, `input_hash` (hash script saat konsep ditulis, untuk status usang yang dihitung), `is_selected`, `edited_by_user`, `prompt_version_id`, `provider_id`, `model` (SET NULL), `job_id` (unik, SET NULL), `created_at`. Unik `(project_id, version)` dan satu `is_selected` per `project_id` (indeks parsial). Aturan versi sama dengan `platform_metadata`: versi LLM tidak pernah diubah, edit pertama membuat versi `edited_by_user` yang terpilih, edit berikutnya memperbarui baris itu (lihat 4.14).

### 2.2 Aset dan render

**`asset`**

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | ulid | |
| `project_id` | fk null | null hanya untuk aset global (gambar referensi Visual Style) |
| `scene_id` | fk null (hapus scene menghapus asetnya) | null untuk aset tingkat project |
| `kind` | enum `voice_clip`, `word_timings`, `image`, `scene_video` (klip video AI per scene 9:16 MP4, durasi dipotong mengikuti narasi, audio bawaan dibuang, sejak Fase 6s), `subtitle_ass`, `subtitle_srt`, `video`, `thumbnail` (frame render), `thumbnail_image` (gambar thumbnail buatan provider gambar, tingkat project, PNG 1080x1920, sejak Fase 6b), `llm_raw`, `reference_image`, `export_zip`, `bgm` (musik latar, tingkat project, `input_hash` = sha256 byte file), `sfx` (efek suara global, `project_id` null, `input_hash` = sha256 byte file, sejak Fase 6c), `watermark` (logo watermark global, `project_id` null, PNG RGBA, `input_hash` = sha256 PNG, sejak Fase 6g) | |
| `version` | int | per `(project_id, scene_id, kind)` |
| `storage_key` | str | |
| `mime`, `size_bytes` | str, int | |
| `duration_s`, `width`, `height` | null | sesuai jenis |
| `data` | JSON null | contoh: timing kata, kecepatan bicara terukur |
| `input_hash` | str | sha256 dari input kanonis, lihat 2.4 |
| `provider_id`, `model`, `params` | null | |
| `is_selected` | bool | maksimal satu `true` per `(scene_id, kind)` |
| `job_id` | fk null | |
| `created_at` | datetime | |

Aset tidak pernah diubah atau ditimpa. Regenerate membuat baris baru lalu memindahkan `is_selected`. Indeks unik `(project, scene, kind, version)` dan satu `is_selected` per `(project, scene, kind)`; versi diambil di dalam `INSERT` itu sendiri. Hash yang sama di project yang sama memakai ulang file lewat baris aset baru yang menunjuk `storage_key` yang sama. Kolom `word_timings`: kata ada di `data.words` (relatif terhadap awal klip asli), `data.clip_asset_id` menautkannya ke klip.

**`render`**: `id`, `project_id`, `script_id`, `version`, `manifest` (JSON: aset terpilih per scene, atribut render tiap scene, gaya subtitle, musik), `manifest_hash`, `status`, `video_asset_id`, `ass_asset_id`, `srt_asset_id`, `thumbnail_asset_id`, `duration_s`, `render_seconds`, `encoder`, `warnings` (daftar teks), `job_id`. Baris ini hanya ditulis untuk render yang berhasil (`status` selalu `completed`), bersama keempat asetnya dalam satu transaksi; kegagalan hidup di job. `AssetKind.bgm` menambah jenis aset musik latar.

**`sfx_slot`** (Fase 6c migrasi 0009, Fase 6f migrasi 0011): `name` (PK, `^[a-z0-9][a-z0-9-]{1,23}$`), `category` (`transition` atau `event`, tidak bisa diubah setelah dibuat), `description` (teks, ikut ke prompt), `asset_id` (aset `sfx` yang diputar, SET NULL), `volume_db` (−30 sampai 0, bawaan −10), `created_at`, `updated_at`. Pustaka global yang diisi pemilik, maksimal 40 slot, satu file per slot. Slot hanya ada selama punya baris; migrasi 0011 mengisi kategori dan keterangan lima slot lama (`whoosh`, `slorot`, `ding`, `pop`, `boom`). Unggah ulang membuat aset baru dan memindahkan `asset_id`; menghapus slot menghapus barisnya, aset dan filenya tetap ada. Kolom `scene.transition_sfx` dan `scene.event_sfx` memuat nama slot (sampai 24 karakter).

**`app_setting.voice_volume_db`** (Fase 6f): volume suara narasi global dalam dB, −12 sampai +6, kelipatan 0,5, bawaan 0. Nilai yang tidak sah dibaca 0.

**`app_setting.watermark`** (Fase 6g): `{enabled, text, opacity_pct, logo_asset_id}`, bawaan mati, teks `@SiKlepon-id`, opacity 65. Teks 1 sampai 32 karakter dan satu baris, opacity 30 sampai 100 kelipatan 5. Nilai yang tidak sah dibaca sebagai mati. Satu pengaturan untuk semua proyek; logo boleh kosong (watermark hanya teks).

### 2.3 Eksekusi, biaya, konfigurasi

**`generation_job`**

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | ulid | |
| `type` | enum `ideas`, `script`, `checks_fix`, `validate`, `revise`, `voice`, `align`, `image`, `video` (job per scene untuk klip video AI, Fase 6s), `image_batch`, `voice_batch`, `render`, `metadata`, `thumbnail_concept`, `thumbnail`, `export`, `provider_test` | |
| `project_id`, `scene_id`, `parent_id` | fk null | |
| `status` | enum `queued` / `processing` / `completed` / `failed` / `cancelled` | |
| `resource_key` | str | contoh `image:01J…`, `video:01J…`, `render`, `gpu:whisper` |
| `input` | JSON | |
| `input_hash` | str | untuk dedup |
| `result` | JSON null | |
| `error` | JSON null | `{kind, message, retryable, detail}` |
| `attempts`, `max_attempts` | int | |
| `priority` | int | lebih kecil lebih dulu |
| `run_after` | datetime | |
| `locked_by`, `heartbeat_at` | null | |
| `cancel_requested` | bool | |
| `progress` | int 0..100 | |
| `progress_message` | str | |
| `prompt_version_id`, `provider_id`, `model` | null | |
| `created_at`, `started_at`, `finished_at` | datetime | |

Unique index parsial: `(type, project_id, scene_id, input_hash)` di mana `status IN ('queued','processing')`. Didukung oleh SQLite dan Postgres.

**`job_event`**: `id`, `job_id`, `ts`, `level`, `message`, `data` (JSON).

**`usage_record`**: `id`, `job_id`, `project_id`, `provider_id`, `model`, `capability`, `input_tokens`, `output_tokens`, `characters`, `images`, `seconds`, `cost_estimate` (decimal null), `currency`, `succeeded` (bool), `created_at`.

`cost_estimate` dan `currency` tidak dipakai (selalu null): biaya dihitung saat dibaca (`services/pricing.py`, `GET /projects/{id}/usage`) dari jumlah `usage_record` per (kemampuan, provider, model) dikali harga di `provider_model`, supaya harga yang diisi atau dikoreksi belakangan langsung berlaku untuk semua catatan. Harga lama tidak diarsipkan. `provider_id` null berarti pekerjaan lokal (align, render), tampil "Lokal, gratis"; karena itu provider yang punya catatan pemakaian tidak boleh dihapus. Provider dry-run (adapter `fake`) tampil "Dry-run, tanpa biaya". Model tanpa harga membuat biayanya "tidak diketahui" dan total ditandai belum lengkap; mata uang berbeda tidak dijumlahkan.

**`provider`**

| Kolom | Tipe | Catatan |
|---|---|---|
| `id` | ulid | |
| `name` | str | |
| `capability` | enum `llm` / `voice` / `image` / `video` | |
| `adapter` | str | kunci di `ADAPTERS` |
| `base_url` | str null | |
| `api_key_encrypted` | bytes null | Fernet |
| `default_model` | str null | |
| `quirks` | JSON | menimpa `caps` bawaan adapter |
| `enabled` | bool | |
| `priority` | int | |
| `created_at`, `updated_at` | datetime | |

**`provider_model`**: `id`, `provider_id`, `name`, `price_input_per_1k_tokens`, `price_output_per_1k_tokens`, `price_per_1k_chars`, `price_per_image`, `currency`. Nama unik per provider (`(provider_id, name)`), harga `Numeric(12, 6)` dan null berarti belum diisi (0 adalah harga gratis yang diketahui), mata uang tiga huruf kapital, ikut terhapus bersama provider. Diisi lewat `PUT /providers/{id}/prices` yang mengganti seluruh daftar. Pemakaian dengan `model` null memakai harga `default_model` provider.

**`visual_style`**: `id`, `name`, `version`, `style_text`, `negative_text`, `mascot_anchor`, `reference_asset_id` (null), `image_params` (JSON), `is_default`.

**`prompt_template`**: `id`, `key` (contoh `script.generate`, `category.animals`), `kind` (`task` / `block` / `category` / `format`), `active_version_id`.

**`prompt_version`**: `id`, `template_id`, `version`, `source` (`builtin` / `user`), `content`, `frontmatter` (JSON), `content_hash`, `created_at`. Tidak pernah diubah setelah dibuat.

**`voice_calibration`**: `provider_id`, `voice_id`, `words_per_second` (rata-rata bergerak), `samples`, `updated_at`.

**`app_setting`**: `key`, `value` (JSON).

**`audit_event`**: `id`, `ts`, `entity`, `entity_id`, `action`, `diff` (JSON tanpa nilai rahasia).

### 2.4 `input_hash`

Hash sha256 dari JSON kanonis (kunci diurutkan, tanpa spasi) berisi semua input yang memengaruhi hasil:

| Aset | Input |
|---|---|
| `voice_clip` | teks voiceover setelah sanitasi, `previous_text`, `next_text`, provider, model, voice, `voice_settings` |
| `word_timings` | hash clip suara, teks, metode (`provider` / `whisper:<model>` / `proportional`) |
| `image` | prompt gambar final hasil `image.compose`, `negative_text`, provider, model, params, hash gambar referensi |
| `thumbnail_concept` | judul, hook, semua voiceover script yang disetujui, kategori, format, bahasa |
| `thumbnail_image` | sama dengan `image`, dengan prompt final hasil `thumbnail.compose` |
| `render` (`manifest_hash`) | id aset terpilih per scene, pengaturan render, gaya subtitle, hash musik latar, dan (hanya bila ada cue SFX yang punya file) aset, hash, dan volume tiap SFX yang dipakai plus daftar cue; `voice_db` hanya bila bukan 0; `watermark` (`v`, teks, opacity, id dan hash logo) hanya bila watermark menyala |

Kegunaan:

- **Status usang:** aset terpilih usang bila `input_hash` yang dihitung dari keadaan scene saat ini berbeda dari milik aset itu.
- **Cache:** sebelum memanggil provider, handler mencari aset di project yang sama dengan `kind` dan `input_hash` sama. Bila ada dan job tidak diberi `force: true`, aset itu dipilih ulang tanpa memanggil API.

---

## 3. Schema output LLM

Semua schema adalah model Pydantic di `app/domain/llm_outputs.py`. Teks `{{ output_contract }}` di prompt dibangkitkan dari model ini (nama field, tipe, enum, batas panjang, contoh), sehingga prompt dan validator selalu sama.

### 3.1 `IdeasOutput` (`ideas.v1`)

```json
{
  "suggested_category": "animals",
  "ideas": [
    {
      "title": "Apakah cicak merasa sakit saat ekornya putus?",
      "angle": "Membahas mekanisme autotomi dan apakah ada rasa sakit",
      "hook": "Cicak memutus ekornya sendiri. Tapi sakit nggak sih?",
      "why_it_works": "Pertanyaan yang sering dipikirkan tapi jarang dijawab",
      "fact_risk": "check",
      "fact_note": "Apakah cicak merasakan nyeri saat ekornya putus belum dipastikan."
    }
  ]
}
```

Aturan bisnis: tepat 8 ide. `title` 20 sampai 90 karakter. Kemiripan antar-judul (rasio token) di bawah 0,8. `suggested_category` harus berupa slug yang ada, bila tidak diganti `null`.

Fase 6d: `fact_risk` wajib. Nilainya `check` bila jawabannya bergantung pada mekanisme yang masih diperdebatkan, hipotesis, atau premis topik yang belum mapan; `fact_note` lalu wajib berisi satu kalimat Indonesia tentang apa yang belum pasti. `low` membuang `fact_note`. Kartu ide menampilkan "Perlu dicek" beserta catatannya, dan catatan itu ikut dikirim ke prompt script supaya poinnya ditulis sebagai dugaan. `angle` ditulis sebagai jawaban konkret tanpa nama mekanisme rasa penasaran; awalan seperti "Hidden logic:" dibuang oleh validator.

### 3.2 `ScriptDraft` (`script.v1`)

```json
{
  "schema_version": "script.v1",
  "title": "Ekor Cicak yang Putus",
  "hook": "Cicak sengaja memutus ekornya sendiri.",
  "scenes": [
    {
      "beat": "hook",
      "voiceover": "Cicak sengaja memutus ekornya sendiri.",
      "subtitle": null,
      "visual_prompt": "Stick figure jumps back in surprise as a gecko's tail drops off on the floor",
      "include_mascot": true,
      "visual_type": "character",
      "transition": "cut",
      "emphasis_words": ["sengaja"],
      "transition_sfx": null,
      "event_sfx": "boom",
      "event_word": "sengaja"
    }
  ],
  "claims_to_verify": ["Ekor cicak bisa tumbuh kembali dalam beberapa minggu"]
}
```

Catatan:

- `start_time`, `end_time`, dan `duration` dari spec awal **tidak diminta dari LLM**. Nilainya dihitung kode dari jumlah kata (estimasi) lalu dari audio asli (final). Ini mencegah angka yang saling bertentangan.
- `visual_prompt` ditulis dalam bahasa Inggris karena ditujukan ke model gambar. Voiceover dan subtitle berbahasa Indonesia.
- `hook` selalu sama dengan narasi scene 1: setiap kali estimasi dihitung ulang (simpan versi, edit, tambah, hapus, urut ulang), `hook` disalin dari scene pertama. Metadata dan konsep thumbnail memakai hook ini.
- Normalizer menerima tag lama `[NO_MASCOT]` di awal `visual_prompt`, menghapusnya, lalu mengisi `include_mascot = false`.
- Jumlah scene 8 sampai 14. `voiceover` 3 sampai 16 kata per scene.
- SFX (Fase 6c, 6f): `transition_sfx` dan `event_sfx` berupa nama slot (string dengan pola nama slot). Selama handler `script`, `checks_fix`, dan `revise` memvalidasi, `SFX_LIBRARY` berisi SFX yang ditawarkan prompt (slot yang punya file); nama lain atau kategori yang salah ditolak dengan pesan berisi daftar yang sah, lalu diminta ulang. Di luar handler hanya pola nama yang dicek. `event_word` yang tidak ada di voiceover (dibandingkan tanpa tanda baca) dikosongkan, `event_word` tanpa `event_sfx` dikosongkan, dan `transition_sfx` scene 1 selalu dikosongkan. Prompt `script.generate`, `script.fix`, dan `script.revise` (v2, block `sfx_rules`) hanya menyebut slot yang sudah berisi file, beserta keterangannya; tanpa file, semua field SFX diminta `null`. Edit scene menerima slot mana pun dengan kategori yang cocok (422 `InvalidScene` "SFX itu tidak ada di pustaka." atau "SFX klik bukan SFX event.").

### 3.3 `ValidationOutput` (`validation.v1`)

```json
{
  "status": "NEEDS_REVISION",
  "score": 72,
  "summary": "Hook kuat, tapi scene 6 dan 7 mengulang informasi yang sama.",
  "issues": [
    {
      "severity": "error",
      "area": "script",
      "scene_position": 6,
      "message": "Scene 6 dan 7 menyampaikan fakta yang sama",
      "suggestion": "Gabungkan, lalu pakai scene 7 untuk fakta regenerasi",
      "needs_change": true
    }
  ],
  "claims_to_verify": ["…"]
}
```

`severity`: `error` / `warning` / `suggestion`. `area`: `content` / `script` / `scenes` / `voiceover` / `platform`. Aturan bisnis: status `PASS` tidak boleh disertai issue `error`. Bila terjadi, status diturunkan menjadi `NEEDS_REVISION`.

Fase 6e: `needs_change` wajib. Sebelum aturan status dijalankan, kode membuang issue dengan `needs_change = false` dan issue yang persis sama (pesan dan scene), lalu menurunkan `error` atau `warning` tanpa `suggestion` menjadi `suggestion`. Bila validator menyebut issue dan semuanya terbuang, `NEEDS_REVISION` naik menjadi `PASS`; vonis tanpa issue sama sekali tetap seperti adanya.

### 3.4 `MetadataOutput` per platform (`metadata.v1`)

| Platform | Field | Batas (tetap) |
|---|---|---|
| `youtube_shorts` | `title`, `description`, `hashtags`, `tags` | judul ≤ 60 karakter, deskripsi ≤ 500, hashtag 3 sampai 5 (termasuk `#shorts`), tag ≤ 10 |
| `tiktok` | `caption`, `hashtags` | caption ≤ 200 karakter, hashtag 3 sampai 5 |
| `facebook_reels` | `caption`, `hashtags` | caption ≤ 300 karakter, hashtag 3 sampai 4 |

Fase 6m menurunkan batas ini (sebelumnya judul 100, deskripsi 1000, caption 300 dan 500, tag 15). Prompt meminta lebih pendek lagi (judul 30 sampai 45, deskripsi ≤ 300, caption TikTok ≤ 150, Reels ≤ 250), jadi minta ulang hanya terjadi bila model benar-benar meleset. Baris lama yang lebih panjang tetap tersimpan; edit berikutnya ditolak sampai teksnya dipendekkan.

Hashtag dinormalisasi: diawali `#`, huruf kecil, tanpa spasi, tanpa duplikat. Hashtag yang isinya lebih dari 24 karakter dibuang (frasa panjang tidak dicari orang). YouTube selalu diakhiri `#shorts`: ditambahkan bila tidak ada, dipindah ke akhir bila ada, dan mengambil tempat terakhir bila daftar sudah penuh. Aturan ini juga berlaku untuk edit pengguna.

Batas ini konstanta di model Pydantic (`YouTubeShortsMetadata`, `TikTokMetadata`, `FacebookReelsMetadata` di `llm_outputs.py`), bukan pengaturan: kontrak output prompt dibangkitkan dari model, jadi batas yang bisa diubah menuntut model dinamis (ditunda). Hashtag dan tag di atas batas atas dipotong oleh normalizer; hashtag di bawah batas bawah, atau judul dan caption yang kelewat panjang, membuat jawaban ditolak dan diminta ulang, tidak pernah dipotong diam-diam. Edit pengguna divalidasi dengan model yang sama (422 `InvalidMetadata`). `GET /projects/{id}/metadata` mengirim batasnya supaya UI menampilkan penghitung.

### 3.5 `ThumbnailConceptOutput` (`thumbnail.concept`, Fase 6b)

`title_text` (Indonesia, 2 sampai 40 karakter, satu baris, 2 sampai 6 kata), `visual_prompt` (Inggris, 20 sampai 800 karakter, aturan maskot sama dengan scene: hanya aksi, pose, ekspresi), `include_mascot`. Jawaban di luar batas ditolak dan diminta ulang, tidak dipotong. Edit pengguna divalidasi dengan model yang sama (422 `InvalidThumbnail` dengan pesan per kolom, mis. "Teks thumbnail maksimal 40 karakter. Sekarang 43.").

---

## 4. Pipeline

### 4.1 Tahap Ideas

- Input: `topic`, `category` (bisa null), `format` (bisa null), `language`.
- Prompt: `ideas.from_topic` bila `topic` terisi, `ideas.discover` bila hanya kategori.
- Output: 8 baris `content_idea` dengan nomor `batch` baru. Bila `category_id` kosong dan `suggested_category` valid, project diisi dengan `category_source = suggested`.
- Gerbang A: endpoint `select` mengisi `selected_idea_id` lalu memanggil `reconcile`, yang meng-enqueue job `script`.

### 4.2 Tahap Script

1. Render prompt `script.generate` dengan ide, aturan kategori, aturan format, blok pacing, blok aturan visual, dan `output_contract`.
2. `StructuredLLM` menghasilkan `ScriptDraft` (lihat 5.2).
3. Simpan sebagai `script` versi baru dengan `source = generated` dan baris `scene`. Hitung `est_duration_s` per scene.
4. Jalankan cek otomatis (4.3). Bila ada pelanggaran berat, jalankan satu kali `script.fix` dengan daftar pelanggaran, simpan sebagai versi baru dengan `source = fixed`, lalu cek lagi.
5. Enqueue `validate`.

### 4.3 Cek otomatis

Fungsi murni `run_checks(scenes, wps, rules) -> list[CheckIssue]`. Setiap issue punya `code`, `severity` (`error` / `warning`), `scene_position`, `message`.

| Kode | Aturan default | Severity |
|---|---|---|
| `scene_count` | 8 ≤ n ≤ 14 | error |
| `duration_range` | total estimasi melebihi `target_max_s` (Fase 11: satu-satunya pagar durasi; estimasi di bawahnya selalu lolos) | error |
| `duration_short` | total estimasi di bawah `target_min_s`, hanya bila `target_min_s` > 0 (Fase 11) | warning |
| `hook_length` | estimasi scene 1 ≤ 3,5 detik | error |
| `scene_too_long` | voiceover > 12 kata atau estimasi > 5 detik (batas keras 16 kata ada di schema) | warning |
| `scene_too_short` | voiceover < 3 kata | warning |
| `visual_repeat` | `visual_type` sama lebih dari 2 kali berturut-turut | warning |
| `mascot_ratio` | maskot di semua scene, atau tidak ada maskot di scene hook | warning |
| `empty_field` | `voiceover` atau `visual_prompt` kosong | error |
| `duplicate_voiceover` | dua scene dengan voiceover identik atau sangat mirip | error |
| `tts_risk` | simbol (`%`, `&`, `/`), angka romawi, singkatan huruf kapital, URL | warning |
| `beat_order` | `hook` bukan scene pertama, `cta` atau `loop` bukan scene terakhir, atau scene terakhir tidak sesuai penutup project | warning |
| `loop_dangling` | scene `loop` terakhir diakhiri titik, tanda seru, atau tanda tanya | warning |
| `written_register` | voiceover memakai kata tulisan: adalah, bahwa, merupakan, tersebut, tak, yaitu, dimana | warning |
| `repeated_opener` | dua scene berurutan diawali kata yang sama, atau "jadi" membuka lebih dari satu scene | warning |
| `numbered_points` | format bernomor (Top 3) tanpa scene yang diawali "Pertama,", "Kedua,", "Ketiga," berurutan | warning |

Estimasi durasi: `kata / wps + 0,15 detik per scene`. Nilai `wps` diambil dari `voice_calibration` untuk suara project: suara yang sudah di-pin, atau (sebelum produksi) suara yang akan di-pin produksi (`provider_router.expected_voice`, aturan yang sama dengan `pin_production_defaults`). Bila belum ada sampel, default 2,3. Dengan begitu batas kata yang diberikan ke LLM saat menulis script sudah memakai kecepatan suara yang sebenarnya.

Pesan `duration_range` menyebut jumlah kata dan kira-kira berapa kata yang perlu dipangkas atau ditambah; pesan `hook_length` menyebut jumlah kata hook dan batas katanya.

Teks `tts_risk` tidak diubah otomatis. Masalah ini dilaporkan supaya LLM (lewat `script.fix` atau `script.revise`) atau pengguna yang memperbaikinya.

### 4.4 Validasi dan revisi

```text
validate(script vN)
  PASS            → script.status = validated → Gerbang B
  NEEDS_REVISION  → bila revisi < max_revisions: revise → vN+1 → checks (→ checks_fix bila ada error) → validate
                    bila tidak: needs_attention → Gerbang B
  FAIL            → needs_attention → Gerbang B
```

- `max_revisions` default 2, bisa diubah per project.
- Validator menerima hasil cek otomatis sebagai konteks, supaya tidak menilai ulang hal yang sudah diukur kode. Payload script memuat `words` dan `est_seconds` per scene serta `total_words` dan `estimated_total_s`, sehingga validator tidak menghitung sendiri.
- Sejak Fase 6e (`validate.script` v3) dua temuan wajib `error` sehingga memicu revisi: scene yang membuka jawaban hook sebelum dua scene terakhir sebelum cta, dan script tanpa satu tips aman bila topik dan kategorinya mengizinkan. `script.revise` v4 menahan jawaban dengan petunjuk atau pertanyaan, dan menaruh tips tanpa menambah total kata. Sejak Fase 6l (`validate.script` v7, `blocks/script_rules`) tips hanya diminta di kategori `fact_check` strict, dan tips yang tidak ada paling tinggi `suggestion`, jadi tidak pernah memicu revisi; kategori lain tidak pernah diminta tips.
- Sejak Fase 6i setiap project memilih penutup video di `settings.ending`: `loop` (bawaan project baru) atau `cta` (project lama tanpa kunci ini). Prompt script (`script.generate` v5, `script.fix` v4, `script.revise` v5, `validate.script` v5) menerima `ending`; blok bersama bercabang dengan `ending is defined`, jadi versi lama tetap berisi aturan CTA. Scene `loop` adalah jembatan 3 sampai 6 kata yang menggantung (tanpa titik) dan menyambung ke hook saat video diputar ulang; hook untuk loop berupa pernyataan atau perintah. Render dan metadata memutuskan loop dari beat scene terakhir, bukan dari setelan project: render loop tanpa hening di ujung (`TAIL_S` 0) dan musik tanpa fade, kunci manifest `ending` dan kunci hash metadata `ending` hanya ada saat loop, sehingga video dan metadata CTA lama tetap memakai hash-nya. Deskripsi YouTube Shorts (`metadata.youtube_shorts` v3) video loop mendapat satu kalimat ajakan subscribe (maksimal 8 kata) sebelum pertanyaan diskusi. Loop visual (gambar terakhir menyerupai scene 1) adalah tahap berikutnya.
- Hook (`blocks/hook_rules`, dipakai prompt ide dan prompt naskah; `script.generate` v4, `validate.script` v4): sesuai batas kata hook di PACING, ketegangan di 5 kata pertama, menyapa penonton, dan tidak pernah membuka jawaban atau penjelasannya. Validator memberi `error` di scene 1 untuk hook yang membuka jawaban (memicu revisi) dan `warning` untuk hook datar atau pertanyaan ya/tidak yang sudah umum.
- Sejak Fase 6m narasi dijaga sebagai satu ucapan (`blocks/narration`, dipakai generate, fix, revise, dan validasi; `blocks/spoken_indonesian` berisi kata tulisan yang dihindari). `validate.script` v8 memberi 20 poin untuk narasi (judul 15, hook 20, akurasi 25, narasi 20, gambar 15, maskot 5); masalah narasi paling tinggi `warning`. `script.revise` v6 membaca ulang semua voiceover sesudah mengubah, tidak memecah kalimat jadi potongan, dan mempertahankan kata jawaban di payoff.
- Sejak Fase 6n payoff adalah satu-satunya scene yang membuka jawaban lengkap (`blocks/narration`). `validate.script` v9 memberi `error` di scene payoff bila payoff hanya mengulang hook atau scene sebelumnya, atau merangkum ("tiga hal itu"). Format Top 3 (v2) mewajibkan ordinal lisan "Pertama,", "Kedua,", "Ketiga,".
- Sejak Fase 6o (`validate.script` v10) setiap issue `error` atau `warning` yang menunjuk satu scene wajib membawa `evidence`, yaitu kutipan kata per kata dari scene itu; untuk pengulangan, `repeats_scene` menunjuk scene yang diulang dan `evidence` mengutip scene itu. Saat handler validasi berjalan (`use_script_lines`), kutipan yang tidak ada di script menurunkan issue (`error` jadi `warning`, `warning` jadi `suggestion`; klaim pengulangan yang tidak terbukti jadi `suggestion`). Bila penurunan ini menghapus error terakhir, NEEDS_REVISION menjadi PASS; FAIL tidak diubah.
- **Versi terbaik:** setelah loop berhenti, `active_script_id` menunjuk ke versi tanpa error cek otomatis (dihitung dari scene saat itu), lalu versi yang validasi terakhirnya tanpa issue `error`, lalu skor tertinggi. Bila seri, versi terbaru yang dipilih. Versi dengan error cek otomatis hanya terpilih bila semua versi punya error.
- Hasil revisi melewati cek otomatis yang sama dengan script baru (`queue_checks_or_validate`): bila ada error, `checks_fix` membuat versi `fixed` sebelum validasi. Versi `fixed` tidak dihitung sebagai revisi untuk `max_revisions`.
- Validasi manual (`POST /scripts/{id}/validate`, input `auto_revise: false`) tidak pernah merevisi dan tidak memindahkan `active_script_id`.
- Loop otomatis (`auto_revise: true`) dirantai dengan `enqueue_once`: satu job per input, idempoten setelah worker mati. `finalize_best` berjalan saat loop berhenti; bila job `revise` atau `validate` otomatis gagal atau dibatalkan di tengah loop, `reconcile` yang memanggilnya. Validasi manual yang gagal tidak memicu `finalize_best`.
- Provider LLM untuk validasi bisa diatur terpisah dari provider untuk generate (`app_setting.validation_provider_id`). Default: provider LLM prioritas tertinggi.

### 4.5 Gerbang B: edit dan persetujuan

- `PATCH /scenes/{id}` menaikkan `revision`, menjalankan ulang cek otomatis secara sinkron (murah), dan mengisi `edited_after_validation = true` bila script sudah divalidasi.
- `POST /scenes/{id}/split` (Fase 6r, tombol "Pecah scene") mengantre job `scene_split` (termasuk rantai script, jadi edit lain terkunci dan stage script `processing`). Worker meminta LLM (`scene.split` v1, output `SceneSplitOutput` berisi tepat 2 scene) menulis ulang scene itu menjadi dua scene lengkap dengan prompt visual; scene asal diisi bagian pertama (id dan SFX transisinya tetap), scene baru disisipkan sesudahnya tanpa SFX transisi. Beat mengikuti scene asal; payoff yang dipecah menjadi `main` lalu `payoff`. Ditolak 422 untuk hook, scene terakhir, dan script yang sudah mencapai batas scene pacing. Scene yang diedit sesudah diminta (`revision` berbeda) dilewati tanpa memanggil LLM. Handler hanya memanggil `reconcile_render`, tetapi seperti job lain, worker lalu menjalankan `reconcile`: pada script yang sudah disetujui, suara dan gambar scene baru langsung diantre (aset yang belum ada), sedangkan aset lama bagian pertama menjadi stale dan menunggu pengguna.
- Tambah, hapus, dan urutkan scene menormalisasi ulang `position`.
- Edit hanya untuk versi aktif dan saat tidak ada job rantai script (`script`, `checks_fix`, `validate`, `revise`) yang aktif; selain itu 409 `ScriptBusy` atau `ScriptNotActive`.
- Daftar klaim yang ditampilkan dan dikonfirmasi adalah klaim script ditambah klaim validasi terakhir. Klaim dengan kemiripan token ≥ 0,7 dianggap satu klaim; rumusan yang datang belakangan (biasanya dari validator) menggantikan yang lama di posisinya.
- `POST /scripts/{id}/approve` (body `claims_confirmed`) butuh semua klaim sudah dicek pengguna (422 `ClaimsNotConfirmed`) dan tidak ada scene dengan narasi atau prompt gambar kosong (409 `EmptyScene`). Hasilnya status `approved`, `active_script_id` terisi, lalu `reconcile`. Hanya satu script `approved` per project: yang lama kembali ke status validasi terakhirnya.
- Setelah disetujui, edit tetap diizinkan. Aset scene yang berubah menjadi usang dan tidak di-regenerate otomatis.

### 4.6 Suara

- Satu job `voice` per scene. Job induk `voice_batch` tidak dibuat: induk tanpa pekerjaan; progres tahap dihitung dari job per scene.
- Teks disanitasi: tanda kutip miring, en dash, dan em dash diganti, spasi berlebih dibuang.
- Untuk provider dengan `supports_context`, kirim `previous_text` dan `next_text` dari scene sebelah.
- Simpan clip asli (`voice_clip`), ukur durasi dengan ffprobe, lalu deteksi hening di tepi dengan filter `silencedetect`. Posisi potong disimpan di `asset.data.trim = {start_s, end_s}` (posisi absolut di klip asli, sisa 0,05 dtk hening di tiap tepi). Klip yang seluruhnya hening, atau yang akan menyusut di bawah 0,3 dtk, tidak dipotong. File asli tidak diubah.
- Bila provider mengembalikan timestamp, simpan sebagai aset `word_timings` (metode `provider`). Bila tidak, enqueue `align`.
- Perbarui `voice_calibration` dengan `kata / (end_s - start_s)`, rata-rata bergerak dari 20 sampel terakhir (rata-rata biasa sampai 20 sampel, sesudahnya `baru = lama + (x - lama) / 20`). Klip di bawah 3 kata atau di luar 1,0 sampai 5,0 kata/dtk diabaikan.

### 4.7 Alignment

- `WordAligner` dengan implementasi `WhisperAligner` dan `ProportionalAligner`.
- `WhisperAligner`: faster-whisper (model default `small`, bisa diatur `WHISPER_MODEL`), `word_timestamps=True`, `language="id"`, device `cuda` dengan `compute_type` dari konfigurasi (default `int8`). Bila CUDA tidak tersedia, pakai CPU.
- Kata hasil Whisper dicocokkan ke kata script dengan `difflib.SequenceMatcher` pada token yang dinormalisasi (huruf kecil, tanpa tanda baca). Kata script yang tidak cocok diberi waktu interpolasi di antara kata cocok di sekitarnya.
- Bila rasio kata yang cocok di bawah 0,6, pakai `ProportionalAligner` dan catat peringatan di job.
- Output: `AlignResult(words=[{word, start, end}], method, match_ratio)` dalam detik relatif terhadap awal clip asli; `align(audio, text, ctx, bounds)` menerima rentang hasil trim untuk pembagian proporsional. Bila CUDA gagal dimuat atau dipakai, Whisper diulang di CPU; bila paket tidak ada atau semua perangkat gagal, hasilnya proporsional dengan peringatan di log job. Job tidak pernah gagal karena Whisper.

### 4.8 Gambar

- Satu job `image` per scene (tanpa induk `image_batch`, lihat 4.6).
- Prompt final dirender dari template `image.compose` dengan input `style_text`, `mascot_anchor` (hanya bila `include_mascot`), `visual_prompt`, `visual_type`, blok zona aman, dan blok teks berbahasa Indonesia.
- Sejak Fase 6p (`image.compose` v2) spasi berlebih di `style_text` dirapikan, `mascot_anchor` selalu diakhiri tepat satu titik, dan kalimat garis lantai hanya ditambahkan untuk `visual_type` `character` dan `environment` (gaya default tidak lagi menyebut garis lantai). Blok `visual_rules` meminta subjek yang berulang ditulis dengan kata yang sama dan label ditulis seperti tercetak ("Rp19.900"); blok `mascot` menggambar orang lain sebagai stick figure hitam tanpa kepala hijau.
- Bila provider `supports_reference_image` dan `include_mascot`, gambar referensi Visual Style ikut dikirim.
- Service mengunduh hasil berupa URL, memverifikasi dengan Pillow, lalu menyesuaikan ke 1080×1920. Gambar dengan rasio berbeda diskalakan sampai menutupi bingkai, lalu di-crop dengan titik pusat vertikal di 40% tinggi (10% di atas tengah), supaya subjek di bagian tengah atas tetap utuh. Permintaan ke relay memakai `size=1024x1792`. Label gambar fake: `NN visual_type` (nomor scene dua digit).
- `retry_safe: false` membuat `max_attempts = 1`.

### 4.9 Render

Lihat bagian 8.

### 4.10 Metadata

- Tiga job `metadata` paralel, satu per platform, masing-masing dengan prompt sendiri.
- Input: script final (judul, hook, semua voiceover), kategori, dan format. Tidak bergantung pada file video. Fase 6m menambah topik yang diketik pemilik (`project.topic`) sebagai petunjuk kata pencarian; topik tidak masuk `input_hash` karena tetap sejak project dibuat, jadi tidak bisa membuat metadata usang dan hash lama tetap berlaku.
- Deskripsi YouTube (`metadata.youtube_shorts` v2) dan caption TikTok serta Reels ditutup satu pertanyaan diskusi: soal kebiasaan, pengalaman, atau pendapat, bukan kuis fakta dan bukan permintaan saran medis, keuangan, atau hukum. Pertanyaan ini hanya di metadata, tidak di narasi.
- Fase 6m (`metadata.youtube_shorts` v4, `metadata.tiktok` v2, `metadata.facebook_reels` v2, block `metadata_style` dan `metadata_hashtags`; versi lama tetap memakai `metadata_rules`): teks memancing rasa penasaran tanpa membocorkan jawaban dan tidak menceritakan ulang narasi per scene; frasa umpan ("Ini jawabannya", "Simak sampai habis") dilarang; baris CTA lisan dan baris loop terakhir diabaikan. Contoh pertanyaan diberi beberapa bentuk (pengalaman, kebiasaan, pendapat, bayangan), dan pola "Kamu tim ... atau tim ...?" tidak lagi jadi bawaan. Hashtag disusun: satu atau dua hashtag topik, satu hashtag kategori dari peta tetap per kategori (misalnya `health` jadi `#faktakesehatan`), satu hashtag jangkauan dari format (`#tahukahkamu`, `#mitosvsfakta`, `#faktamenarik`) atau `#faktaunik`, lalu `#shorts` khusus YouTube. Tanpa `#fyp`, `#foryou`, `#viral`.
- Dijalankan oleh `reconcile` setelah render pertama selesai, atau lebih awal lewat tombol setelah Gerbang B.
- Provider: rantai LLM yang sama dengan tahap script lewat `generate_structured` (prioritas, lalu cadangan). Tidak ada setting provider khusus metadata.
- `input_hash` = hash dari judul, hook, semua voiceover script yang disetujui, kategori, format, bahasa, dan platform. Versi terpilih `ready` bila hash-nya sama dengan keadaan script sekarang, selain itu `stale`. Tidak disimpan.
- Handler menulis baris bersama `job_id`; retry setelah worker mati memakai baris itu tanpa memanggil LLM lagi. Job yang menunggu lalu berjalan setelah script berubah mencatat hash yang benar-benar dipakainya.
- Otomatis (`reconcile`) memakai `enqueue_once`. Klik "Buat ulang" (`POST /projects/{id}/metadata/generate`, opsional per platform) selalu membuat versi baru yang terpilih; versi lama, termasuk hasil edit, tetap ada dan bisa dipilih lagi lewat `POST /metadata/{id}/select`.
- Edit (`PATCH /metadata/{id}`) hanya untuk versi terpilih (409 `MetadataNotSelected`). Versi hasil LLM tidak pernah diubah: edit pertama membuat versi baru `edited_by_user = true` yang terpilih (dengan `input_hash` versi asalnya), edit berikutnya pada versi buatan pengguna memperbarui baris itu. Edit tidak pernah memanggil LLM.

### 4.11 Export

Job `export` menyusun zip sesuai PRD bagian 6 dari render terpilih dan metadata terpilih, lalu menyimpannya sebagai aset `export_zip`.

- Isi persis delapan file, urutan tetap: `video.mp4`, `subtitles.srt`, `subtitles.ass`, `thumbnail.jpg`, `metadata/youtube_shorts.txt`, `metadata/tiktok.txt`, `metadata/facebook_reels.txt`, `project.json`. Teks UTF-8. Gambar per scene, klip suara, musik, dan `llm_raw` tidak ikut.
- `project.json` (`project.v1`): judul dan topik project, script final dengan semua field teks scene, info render (versi, durasi, encoder, peringatan), aset yang dipakai (jenis, nomor scene, versi, `asset_id`, `input_hash`, nama provider dan model), metadata terpilih, peringatan ekspor, dan `exported_at`. Tanpa path lokal, `storage_key`, URL, atau kunci.
- Hanya atas klik pengguna (`POST /projects/{id}/export`), tidak pernah oleh `reconcile`. Butuh render terpilih dengan keempat filenya dan metadata terpilih untuk ketiga platform (409 `ExportNotReady` dengan alasannya); tanpa script disetujui 409 `ScriptNotApproved`. Render atau metadata usang diizinkan dan dicatat sebagai peringatan di hasil job dan `project.json`. Paket yang sudah sesuai menjawab 409 `ExportUpToDate` kecuali `force`; job aktif dikembalikan dengan `created=false`.
- `export_hash` memuat id render dan `manifest_hash`, id keempat aset file, id dan isi teks metadata terpilih (supaya edit di tempat membuat zip usang), dan hash `project.json` tanpa `exported_at` (supaya edit script atau peringatan baru juga membuat zip usang). Zip selalu baris aset baru (versi naik, `input_hash = export_hash`); hash yang sama tanpa `force` memakai ulang file yang tersimpan (`cached`) tanpa menyusun ulang.
- Nama unduhan: judul project sebagai ASCII huruf kecil, angka, dan tanda hubung, maksimal 60 karakter, cadangan `video.zip`. `GET /files` menyajikan `.zip` sebagai `application/zip`.
- Lokal dan gratis: tidak menulis `usage_record`. File aset yang hilang dari disk membuat job gagal dengan `ExportFileMissing`.
- `thumbnail.jpg` (Fase 6b): bila ada aset `thumbnail_image` terpilih, file itu yang dipakai (PNG dikonversi ke JPEG kualitas 90, RGB, di folder sementara; file sumber tidak diubah; tetap 1080x1920). Bila belum ada, frame render tetap dipakai dan peringatan "Thumbnail belum dibuat, memakai frame video." ditambahkan (tidak memblokir). Id aset yang dipakai masuk `export_hash` dan `project.json`, jadi versi gambar baru membuat zip usang. Akibatnya zip yang dibuat sebelum Fase 6b menjadi usang satu kali (peringatan baru masuk `project.json`).

### 4.12 `reconcile(project_id)`

Fungsi idempoten yang dipanggil setelah setiap job selesai atau gagal, dan setelah setiap aksi pengguna yang mengubah keadaan.

Pembagian tugas: rantai script → cek → validasi → revisi bersifat linear, jadi dirantai langsung oleh handler masing-masing (4.2, 4.4). `reconcile` memulai rantai itu (setelah Gerbang A) dan mengurus seluruh tahap produksi setelah Gerbang B, karena di sana banyak job paralel per scene yang bisa usang dan diulang sendiri-sendiri.

```text
bila selected_idea ada dan belum ada script untuk ide itu       → enqueue script
bila script.status = approved:
    untuk setiap scene: voice_clip terpilih tidak ada            → enqueue voice
                        word_timings tidak ada untuk clip itu    → enqueue align
                        image terpilih tidak ada                 → enqueue image
    (aset yang ADA tapi usang tidak di-enqueue, hanya ditandai; langkah yang jobnya sudah ada
     dalam status apa pun, termasuk gagal, tidak di-enqueue lagi: mengulang adalah klik pengguna)
    bila semua slot suara dan gambar `ready` (bukan usang, hilang, gagal, atau berjalan),
         settings.auto_render (bawaan aktif), tidak ada job render aktif, dan render terpilih
         tidak ada atau manifest_hash-nya berbeda dari keadaan sekarang → enqueue render
         (job render terbaru yang gagal atau dibatalkan untuk hash yang sama tidak diulang)
    bila belum ada konsep thumbnail terpilih dan project belum punya job thumbnail_concept
         dalam status apa pun                                    → enqueue thumbnail_concept (enqueue_once)
    bila ada konsep terpilih, belum ada thumbnail_image terpilih, dan project belum punya job
         thumbnail dalam status apa pun                          → enqueue thumbnail (enqueue_once)
    bila ada render terpilih (usang atau tidak) dan platform belum punya versi metadata
         maupun job metadata dalam status apa pun                → enqueue metadata (enqueue_once)
```

Thumbnail (`_thumbnail_start`, setelah `_production_start` karena gambar butuh provider dan gaya yang dipin di sana) dibuat otomatis hanya sekali per project: syaratnya "tidak ada job jenis itu untuk project ini", bukan per hash. Konsep atau gambar yang gagal, dibatalkan, atau usang (script, konsep, gaya, atau provider berubah) tidak pernah dibuat ulang otomatis; pengguna mengklik "Buat konsep"/"Tulis ulang konsep" atau "Buat gambar"/"Buat ulang gambar". Tanpa provider LLM, provider gambar, atau gaya visual, langkahnya dicatat sebagai peringatan log dan dilewati. Langkah ini tidak memanggil `production_status` atau `current_snapshot`.

Metadata dibuat otomatis hanya sekali per platform. Metadata usang atau gagal tidak dibuat ulang otomatis: mengulang adalah klik pengguna. Export tidak pernah di-enqueue oleh `reconcile`. Langkah metadata hanya membaca script yang disetujui dan render terpilih, tidak memanggil `production_status` atau `current_snapshot` (keduanya sudah dipanggil `_render_start`).

Render gratis, jadi `reconcile` membuatnya sendiri; aset berbayar tetap menunggu pengguna. Edit scene (isi, sorotan, transisi, urutan, hapus, tambah) dan pemilihan versi aset memanggil `reconcile_render`, yang hanya mengurus langkah render dan tidak pernah membuat suara, gambar, atau metadata. Job render memakai `enqueue` biasa, bukan `enqueue_once`: hash yang kembali ke nilai lama perlu job baru, yang lalu memakai cache render tanpa FFmpeg. Menyetujui versi script baru membatalkan job suara, align, dan gambar milik scene versi lain serta semua job render, metadata, export, `thumbnail_concept`, dan `thumbnail`; menyetujui ulang versi yang sudah aktif tidak membatalkan apa pun.

Dedup dijamin oleh unique index job aktif. Bila sudah ada job aktif dengan `input_hash` yang sama, enqueue diabaikan.

### 4.13 Status pipeline (dihitung)

`GET /projects/{id}/pipeline` mengembalikan daftar tahap: `ideas`, `idea_selection`, `script`, `validation`, `voice`, `images`, `render`, `metadata`, `export`. Thumbnail bukan tahap (statusnya di `GET /projects/{id}/thumbnail`, lihat 4.14). Setiap tahap berisi:

```json
{
  "stage": "images",
  "state": "processing",
  "done": 7, "total": 10, "failed": 1, "stale": 0,
  "active_job_ids": ["…"],
  "last_error": {"kind": "ProviderTimeout", "message": "…", "scene_position": 4}
}
```

`state`: `waiting` / `ready` / `processing` / `completed` / `partial` / `failed` / `stale`. Nilainya dihitung dari job dan aset, tidak disimpan di tabel. `last_error` juga memuat `job_id` job yang gagal, supaya UI bisa membuka log-nya. Tahap `ideas`: `done` = jumlah batch, `total` = jumlah batch ditambah satu bila ada job aktif.

Tahap `voice` dan `images`: dihitung per scene dari aset terpilih dan `input_hash` yang dihitung ulang dari keadaan scene sekarang. Satu slot: `processing` bila ada job aktif; `ready` bila hash cocok (suara: dan timing kata untuk klip itu ada); `stale` bila ada aset terpilih dengan hash berbeda; `failed` bila job terbaru gagal dan belum ada aset; selain itu `missing`. Tahap `waiting` tanpa script disetujui; `processing` bila ada slot berjalan; `completed` bila semua `ready`; `failed`/`partial` bila ada slot gagal tanpa/dengan slot siap; `stale` bila semuanya siap atau usang dan ada yang usang; selain itu `ready`. Tanpa provider, tahap `failed` dengan `last_error.kind` `NoVoiceProvider`/`NoImageProvider`. Hanya `input_hash` yang menentukan usang: mengubah `emphasis_words`, `transition`, atau `beat` tidak menandai aset.

Tahap `render`, urutan prioritas: `waiting` tanpa script disetujui; `processing` bila ada job render aktif; bila aset belum lengkap, `stale` bila sudah ada render terpilih, selain itu `waiting`; `completed` bila `manifest_hash` render terpilih sama dengan keadaan sekarang; `failed` bila job terbaru gagal untuk hash sekarang; `stale` bila ada render terpilih; selain itu `ready`. Manifest memuat id aset terpilih, trim, `transition`, `visual_type`, `subtitle_override`, `emphasis_words`, gaya subtitle, musik, dan kunci `sfx` (`sounds` per nama: `asset_id`, `input_hash`, `volume_db`; `cues`: `scene_id`, `kind`, `name`, `word`) yang hanya ada bila SFX proyek menyala dan minimal satu cue punya file, sehingga proyek tanpa SFX mempertahankan hash lamanya; perubahan `beat`, `visual_prompt`, atau `voiceover` tidak mengubahnya (yang berubah adalah aset).

Tahap `metadata`: `waiting` tanpa script disetujui; selain itu dihitung seperti `voice` dan `images` dengan tiga slot (satu per platform). Satu slot: `processing` bila ada job metadata aktif untuk platform itu; `ready` bila versi terpilih ada dan `input_hash`-nya sama dengan hash script sekarang; `stale` bila versi terpilih ada dengan hash berbeda; `failed` bila job terbaru gagal dan belum ada versi; selain itu `missing`.

Tahap `export`, urutan prioritas: `waiting` tanpa script disetujui; `processing` bila ada job export aktif; bila bahan belum lengkap (render atau salah satu metadata terpilih belum ada), `stale` bila sudah ada zip terpilih, selain itu `waiting`; `completed` bila `input_hash` zip terpilih sama dengan `export_hash` sekarang; `failed` bila job terbaru gagal untuk hash sekarang; `stale` bila ada zip terpilih; selain itu `ready`.

Tahap `script` (job `script`, `checks_fix`): `waiting` tanpa ide terpilih; `processing` bila ada job aktif; `completed` bila ide terpilih punya script; `failed` bila job terbaru gagal dan belum ada script; selain itu `ready`. `done` = jumlah versi script untuk ide itu.

Tahap `validation` (job `validate`, `revise`), urutan prioritas: `waiting` tanpa script aktif; `processing` bila ada job aktif; `completed` bila script aktif `approved`; `failed` bila job terbaru gagal; `stale` bila `edited_after_validation`; `completed` bila `validated`; `partial` bila `needs_attention`; selain itu `ready`. `done` = jumlah `validation_result` untuk ide itu.

### 4.14 Thumbnail (Fase 6b)

Satu gambar sampul 9:16 per project dengan teks judul pendek tergambar di dalamnya, terpisah dari frame render (`AssetKind.thumbnail` tetap dibuat render sebagai cadangan dan poster pemutar).

- **Konsep** (job `thumbnail_concept`, resource `llm:<provider>`, kebijakan retry seperti LLM): prompt `thumbnail.concept` dari judul, hook, semua voiceover script yang disetujui, kategori, format, dan bahasa; keluaran `ThumbnailConceptOutput` (3.5) lewat `run_structured`. Handler menulis baris `thumbnail_concept` bersama `job_id` (retry memakai baris itu tanpa LLM) dan mencatat hash yang benar-benar dipakai. Konsep `stale` bila `input_hash`-nya berbeda dari hash script sekarang; dihitung, tidak disimpan.
- **Gambar** (job `thumbnail`, `capability=image`, resource `image:<provider>`, berbagi slot dengan gambar scene, retry seperti `image`): prompt final dirender tanpa LLM dari `thumbnail.compose` (gaya, jangkar maskot bila `include_mascot`, `visual_prompt`, instruksi menggambar `title_text` persis, besar, Bahasa Indonesia, tanpa teks lain, blok `image_text`). Hash memakai `image_hash_for` seperti gambar scene, jadi cache dan status usang mengikuti 2.4: edit konsep, gaya, atau provider membuat gambar `stale`. Hasilnya disesuaikan ke 1080x1920 dan disimpan lewat `add_asset(kind=thumbnail_image, scene_id=None)` dengan `data.prompt` dan `data.title_text`, plus `usage_record`.
- **Status** (`GET /projects/{id}/thumbnail`): `state` keseluruhan `waiting` (tanpa script disetujui) / `processing` / `failed` / `stale` / `ready` / `missing`, konsep terpilih dan semua versinya (dengan `stale` per versi), slot konsep (`concept_job`) dan slot gambar (`image`), masing-masing dengan `state`, `job_id`, `error`, dan `last_error` (galat job terbaru bila gagal dan tidak ada job aktif, juga saat versi lama masih tampil siap atau usang), serta semua versi gambar.
- **Edit** (`PATCH /thumbnail/concepts/{id}`, minimal satu kolom): hanya versi terpilih (409 `ConceptNotSelected`), aturan versi seperti metadata (2.1), tidak pernah memanggil LLM atau gambar. Versi konsep lama dipilih lagi lewat `POST /thumbnail/concepts/{id}/select`; versi gambar lama lewat `POST /thumbnail/images/{id}/select`.
- **Buat ulang**: `POST /projects/{id}/thumbnail/concept` (tulis ulang lewat LLM; versi lama termasuk edit tetap ada) dan `POST /projects/{id}/thumbnail/image` (tanpa body, selalu versi baru dari konsep terpilih, tanpa cache). Keduanya 202; job aktif dikembalikan dengan `created=false`; 409 `ScriptNotApproved`, `NoLlmProvider`, `NoThumbnailConcept`, `NoVisualStyle` (dari `NoVisualStyleError`, subkelas `LookupError` di `image_context`), atau galat provider gambar.
- Otomatis hanya pembuatan pertama (4.12). Ketepatan ejaan teks di gambar tidak dijamin dan tidak dicek otomatis (tanpa OCR); pengguna melihat hasilnya lalu membuat ulang.
- UI: kartu "Thumbnail" di atas grid scene tab Produksi (tanpa tombol primary); "Tulis ulang konsep" dan "Pakai konsep ini" nonaktif selama ada perubahan konsep yang belum disimpan. Tab Ekspor punya baris syarat "Thumbnail" yang tidak memblokir.

---

## 5. Provider

### 5.1 Kontrak

```python
@dataclass
class CallContext:
    job_id: str | None
    progress: Callable[[int, str], Awaitable[None]]
    cancelled: Callable[[], bool]
    log: Callable[[str, str, dict | None], Awaitable[None]]

class LLMProvider(Protocol):
    caps: LLMCaps
    async def generate_text(self, req: TextRequest, ctx: CallContext) -> TextResult: ...

class VoiceProvider(Protocol):
    caps: VoiceCaps
    async def synthesize(self, req: VoiceRequest, ctx: CallContext) -> VoiceResult: ...
    async def list_voices(self) -> list[VoiceInfo]: ...

class ImageProvider(Protocol):
    caps: ImageCaps
    async def generate_image(self, req: ImageRequest, ctx: CallContext) -> ImageResult: ...

class Storage(Protocol):
    async def put(self, key: str, data: bytes | Path, mime: str) -> StoredObject: ...
    async def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def local_path(self, key: str) -> Path: ...
    def public_url(self, key: str) -> str: ...
    async def delete(self, key: str) -> None: ...

class WordAligner(Protocol):
    async def align(self, audio: Path, text: str, ctx: CallContext) -> list[WordTiming]: ...

class VideoRenderer(Protocol):
    async def render(self, plan: RenderPlan, ctx: CallContext, workdir: Path) -> RenderResult: ...
# RenderResult: video_path, thumbnail_path, ass_path, srt_path, duration_s, encoder, render_seconds.
# `workdir` adalah folder sementara milik handler, yang menyimpan file ke Storage lalu menghapusnya.
```

| Model | Field |
|---|---|
| `TextRequest` | `messages: list[Message]` (role `system` / `user` / `assistant`), `model`, `temperature`, `max_tokens`, `response_schema: type[BaseModel] \| None` |
| `TextResult` | `text`, `usage: Usage`, `model`, `latency_ms` |
| `VoiceRequest` | `text`, `voice_id`, `model`, `language`, `speed`, `pitch`, `style`, `previous_text`, `next_text` |
| `VoiceResult` | `audio: bytes`, `mime`, `word_timings: list[WordTiming] \| None`, `usage` |
| `ImageRequest` | `prompt`, `negative_prompt`, `aspect_ratio`, `reference_images: list[bytes]`, `seed`, `model`, `extra: dict` |
| `ImageResult` | `image: bytes`, `mime`, `width`, `height`, `revised_prompt`, `usage` |
| `Usage` | `input_tokens`, `output_tokens`, `characters`, `images`, `seconds` |

### 5.2 `StructuredLLM`

```text
render prompt → pilih mode dari caps.structured:
    json_schema  → kirim response_format json_schema
    json_object  → kirim response_format json_object, kontrak di prompt
    none         → kontrak di prompt
→ panggil provider → parse:
    buang <think>…</think>, ambil isi code fence, ambil objek JSON terluar,
    hapus koma berlebih, perbaiki escape yang tidak valid   (port dari v1)
→ validasi Pydantic + aturan bisnis
→ jawaban terpotong (`finish_reason=length`): diminta ulang dengan batas token dua kali lipat (maksimal 16000) dan pesan bahwa balasan terpotong
→ gagal: satu retry dengan balasan model + pesan error spesifik
→ masih gagal: MalformedOutputError, lalu provider LLM berikutnya sesuai prioritas
```

Setiap panggilan menyimpan prompt yang sudah dirender dan respons mentah sebagai aset `llm_raw`.

### 5.3 Registry dan caps

```python
ADAPTERS: dict[tuple[Capability, str], type] = {
    ("llm", "openai_compatible"): OpenAICompatibleLLM,
    ("llm", "fake"): FakeLLM,
    ("voice", "openai_compatible"): OpenAICompatibleVoice,
    ("voice", "elevenlabs"): ElevenLabsVoice,
    ("voice", "edge_tts"): EdgeTTSVoice,
    ("voice", "aistudio"): AIStudioVoice,
    ("voice", "fake"): FakeVoice,
    ("image", "openai_compatible"): OpenAICompatibleImage,
    ("image", "fake"): FakeImage,
    ("video", "openai_compatible"): OpenAICompatibleVideo,
    ("video", "fake"): FakeVideo,
}
```

Adapter `aistudio_job` dan `cloudflare_worker` masuk NICE TO HAVE.

`caps` efektif = `caps` bawaan kelas adapter yang ditimpa `provider.quirks`. Kunci quirks yang dikenal:

| Kunci | Kemampuan | Arti |
|---|---|---|
| `system_role` | llm | `false`: semua pesan system digabung ke awal pesan user pertama |
| `structured` | llm | `none` / `json_object` / `json_schema` |
| `strips_think` | llm | respons bisa diawali blok `<think>` |
| `returns_timestamps` | voice | |
| `supports_context` | voice | menerima `previous_text` / `next_text` |
| `model_template` | voice | contoh `gemini/{model}/{voice}` |
| `extra_body` | semua | field tambahan di body request, boleh memakai `{language}` |
| `supports_reference_image` | image | |
| `accepts_size` | image | `false`: jangan kirim `size` |
| `supports_negative_prompt` | image | `false`: teks negatif digabung ke prompt |
| `aspect_ratio` | video | rasio video (bawaan `9:16`) |
| `response_format` | video | format respons output (`url` bawaan / `b64_json`) |
| `default_voice` | voice | suara bila permintaan tidak menyebut suara (tes koneksi, project yang belum memilih) |
| `models` | voice | daftar model yang bisa dipilih per project di Pengaturan produksi (`voice_settings.model`, menggantikan `default_model`); hanya clip project itu yang jadi usang, tanpa fallback otomatis |
| `retry_safe` | semua | `false`: tidak ada retry otomatis, job terputus ditandai gagal |
| `max_concurrency` | semua | batas `resource_key` |
| `timeout_s` | semua | |

Key yang tidak dikenal ditolak saat menyimpan provider.

**`ProviderRouter.candidates(capability, project)`** mengembalikan daftar provider berurutan: override project, lalu provider `enabled` diurutkan `priority`. Untuk `voice`, `image`, dan `video`, daftar dipotong menjadi satu provider, kecuali `project.settings.allow_image_fallback = true` untuk gambar.

### 5.4 Pemetaan endpoint pemilik (seed awal dari `.env`)

| Provider | `capability` / `adapter` | `quirks` |
|---|---|---|
| Router LLM (`LLM_BASE_URL`, `LLM_MODEL`) | llm / `openai_compatible` | `{"system_role": false, "structured": "json_object", "strips_think": true, "max_concurrency": 4}` |
| Relay flow_bridge (`http://127.0.0.1:8001/v1`, model `nano-banana-2`) | image / `openai_compatible` | `{"retry_safe": false, "accepts_size": true, "supports_reference_image": false, "supports_negative_prompt": false, "timeout_s": 900, "max_concurrency": 1}` |
| Relay flow_bridge video (`http://127.0.0.1:8001/v1`, model `Omni Flash 1.1`) | video / `openai_compatible` | `{"retry_safe": false, "aspect_ratio": "9:16", "response_format": "url", "timeout_s": 300, "max_concurrency": 1}` |

Relay adalah provider gambar dan video. Kenari tidak dipakai. Relay image menerima `size` dan mengubahnya ke rasio Flow terdekat (`1024x1792` → `9:16`). Relay video menerima `POST /v1/videos/generations` (`aspect_ratio="9:16"`, `response_format="url"`), menghasilkan MP4 yang diunduh dari `/v1/videos/files/...`, dan dipotong durasinya di FFmpeg mengikuti narasi audio scene dengan audio bawaan dibuang.
| ElevenLabs | voice / `elevenlabs` | `{"returns_timestamps": true, "supports_context": true, "max_concurrency": 3}` |
| Gemini TTS lewat router | voice / `openai_compatible` | `{"model_template": "gemini/{model}/{voice}", "extra_body": {"language": "Indonesian"}, "returns_timestamps": false}` |
| Edge TTS | voice / `edge_tts` | `{"returns_timestamps": true}` |
| AI Studio TTS (service lokal playwright-gaistudio, `http://localhost:3740`) | voice / `aistudio` | `{"returns_timestamps": false, "default_voice": "Zephyr", "extra_body": {"style": "Vocal Smile", "pace": "Natural", "accent": "Neutral"}, "max_concurrency": 2, "timeout_s": 300}` |

AI Studio TTS memakai API job async: `POST /api/tts/jobs`, poll `GET /api/tts/jobs/{id}` (jeda 0,5 s naik sampai 3 s), lalu `GET /api/tts/jobs/{id}/audio`; header `x-api-key`. Service mengerjakan satu job per waktu, jadi `max_concurrency` 2 membuat job berikutnya sudah antre di service. Saat batas `timeout_s` atau cancel, adapter memanggil `DELETE /api/tts/jobs/{id}`. Service mati, job `failed` (sesi login Google habis) dan `cancelled` menjadi `ServiceDownError` yang tidak di-retry dan tidak pindah ke provider lain. Style per project (`voice_settings.style`) menimpa style di `extra_body`. Daftar suaranya sembilan persona dari v1 (Zephyr, Puck, Charon, Achird, Fenrir, Iapetus, Orus, Rasalgethi, Achernar); `VoiceInfo.description` membawa karakter tiap suara dan pengaturan produksi menampilkannya di bawah pilihan Suara. Seed-nya punya marker sendiri `seed.voice.aistudio`, sehingga DB yang provider suaranya sudah di-seed tetap mendapatkannya sekali.

### 5.5 Error

`app/providers/errors.py`:

| Kelas | `retryable` | Dipetakan dari |
|---|---|---|
| `AuthError` | tidak | 401, 403 |
| `RateLimitError` | ya, menghormati `retry_after` | 429 |
| `ProviderTimeout` | `caps.retry_safe` | timeout klien |
| `ContentPolicyError` | tidak | 400 dengan kode atau pesan kebijakan konten |
| `BadRequestError` | tidak | 400, 404, 422 lainnya |
| `ServerError` | ya | 5xx, koneksi putus |
| `MalformedOutputError` | ya, sekali | parse atau validasi gagal |

Setiap error membawa `message_id` (pesan untuk pengguna dalam bahasa Indonesia) dan `detail` (cuplikan respons vendor, maksimal 500 karakter, tanpa header).

### 5.6 Provider `fake`

- `FakeLLM`: mengembalikan fixture JSON per `task` dari `tests/fixtures/llm/`, atau JSON minimal yang valid dan dibangkitkan dari schema.
- `FakeVoice`: audio sinus 220 Hz dengan panjang `kata / 2,5` detik, plus timing kata proporsional.
- `FakeImage`: PNG 1080×1920 berwarna polos dengan nomor scene dan `visual_type` tertulis di tengah.
- Bisa dipilih di Settings untuk dry-run, dan dipakai oleh tes integrasi.

---

## 6. Prompt

### 6.1 File

```text
app/prompts/
├── tasks/<task>/v<N>.md      ideas.from_topic, ideas.discover, script.generate,
│                             script.fix, script.revise, validate.script,
│                             metadata.youtube_shorts, metadata.tiktok,
│                             metadata.facebook_reels, image.compose,
│                             thumbnail.concept, thumbnail.compose
├── blocks/<name>.md          pacing, visual_rules, mascot, spoken_indonesian, safe_zone
├── categories/<slug>.md
└── formats/<slug>.md
```

Frontmatter untuk task:

```yaml
task: script.generate
version: 1
description: Script dan scene dari ide terpilih
inputs: [idea, category, format, pacing, style, language]
output: ScriptDraft
temperature: 0.8
max_tokens: 4000
```

Frontmatter kategori: `name`, `description`, `fact_check`, `version`. Frontmatter format: `name`, `description`, `version`.

Isi task dibagi dengan penanda `## [system]` dan `## [user]`. Blok dipanggil dengan `{% include "blocks/<name>.md" %}`. Aturan kategori dan format tersedia sebagai `{{ category.rules }}` dan `{{ format.rules }}`. Kontrak output tersedia sebagai `{{ output_contract }}`.

Bahasa: instruksi berbahasa Inggris. Contoh, voiceover, subtitle, dan metadata berbahasa Indonesia. `visual_prompt` berbahasa Inggris.

### 6.2 Versi

- Saat startup, setiap file disinkronkan: bila `content_hash` belum ada untuk template itu, dibuat `prompt_version` baru dengan `source = builtin`. Bila template belum punya versi aktif, versi ini langsung aktif. Selama versi aktif sebuah template berasal dari `builtin`, versi aktif mengikuti file di disk (untuk task: file `vN.md` dengan N terbesar), jadi edit maupun pengembalian file langsung berlaku (PRD 5). Bila versi aktifnya `user`, versi aktif tidak diubah.
- Pengguna (NICE TO HAVE: lewat UI) menyimpan versi baru dengan `source = user`. Versi lama tidak pernah diubah.
- Setiap job mencatat `prompt_version_id`. Prompt yang sudah dirender disimpan di aset `llm_raw`.

### 6.3 `PromptService`

```python
render(task: str, inputs: dict) -> RenderedPrompt
# RenderedPrompt: task, messages, version_id, temperature, max_tokens, output_model
# Aturan kategori dan format masuk lewat inputs; parameter project ditambah bila kelak dibutuhkan.
```

Validasi saat menyimpan versi: Jinja bisa di-parse, variabel yang tidak dikenal (`meta.find_undeclared_variables` dibanding `inputs`) ditolak, `{{ output_contract }}` wajib ada pada task yang punya `output`.

---

## 7. Sistem job

### 7.1 Mengambil job

SQLite (satu worker):

```sql
UPDATE generation_job
SET status = 'processing', locked_by = :worker, heartbeat_at = :now,
    started_at = :now, attempts = attempts + 1
WHERE id = (
  SELECT id FROM generation_job
  WHERE status = 'queued' AND run_after <= :now
    AND resource_key NOT IN (:full_keys)
  ORDER BY priority, created_at
  LIMIT 1
)
RETURNING *;
```

Postgres memakai subquery yang sama dengan `FOR UPDATE SKIP LOCKED`. `full_keys` adalah `resource_key` yang jumlah job `processing`-nya sudah mencapai batas.

Worker berjalan sebagai satu event loop asyncio dengan batas global `WORKER_CONCURRENCY` (default 6), mengecek antrean setiap 1 detik, dan langsung mengecek lagi setelah sebuah job selesai.

### 7.2 Batas sumber daya

| `resource_key` | Batas |
|---|---|
| `llm:<provider_id>` | `quirks.max_concurrency`, default 4 |
| `voice:<provider_id>` | `quirks.max_concurrency`, default 3 |
| `image:<provider_id>` | `quirks.max_concurrency`, default 2 |
| `gpu:whisper` | 1 |
| `render` | 1 |
| `local` (export, induk batch) | 4 |

### 7.3 Retry dan backoff

| Jenis | `max_attempts` | Jeda sebelum percobaan ke-2, ke-3 |
|---|---|---|
| `ideas`, `script`, `checks_fix`, `validate`, `revise`, `metadata`, `thumbnail_concept` | 3 | 5 detik, 20 detik (+ jitter ±20%) |
| `voice` | 3 | 5 detik, 20 detik. `RateLimitError` memakai `retry_after` |
| `image`, `thumbnail` | 2, atau 1 bila `retry_safe: false` | 10 detik |
| `align`, `render`, `export` | 2 | langsung |

Error yang tidak `retryable`, atau percobaan yang habis, membuat status `failed`.

### 7.4 Heartbeat dan job terputus

- Handler yang sedang berjalan memperbarui `heartbeat_at` setiap 10 detik dari task latar.
- Saat worker mulai, dan setiap 30 detik sesudahnya, job `processing` dengan `heartbeat_at` lebih tua dari 60 detik dianggap terputus:
  - bila `retry_safe` dan percobaan masih ada → `queued`
  - bila tidak → `failed` dengan `error.kind = "WorkerInterrupted"` dan pesan yang menyarankan pengecekan manual

### 7.5 Pembatalan

- `queued` → langsung `cancelled`.
- `processing` → `cancel_requested = true`. `ctx.cancelled()` dicek di antara langkah. Proses FFmpeg dihentikan dengan `terminate()`. Request HTTP yang sedang berjalan ditunggu sampai selesai, lalu hasilnya dibuang.

### 7.6 Progress dan log

- `ctx.progress()` menulis ke DB maksimal sekali per detik per job.
- Render memakai `-progress pipe:1` dari FFmpeg: `out_time_ms ÷ total durasi`.
- `ctx.log()` menulis `job_event`.

### 7.7 Urutan tulis

1. Handler menulis file ke Storage dengan key yang memuat ULID aset baru.
2. Dalam satu transaksi: insert `asset`, pindahkan `is_selected`, set job `completed`, insert `usage_record`.
3. Panggil `reconcile`.

Pembersih berkala menghapus file di Storage yang tidak punya baris `asset` dan berumur lebih dari 24 jam.

### 7.8 Shutdown

Sinyal berhenti membuat worker tidak mengambil job baru, menunggu job berjalan sampai 30 detik, lalu keluar. Job yang belum selesai ditangani oleh mekanisme heartbeat saat worker berikutnya mulai.

---

## 8. Render

### 8.1 `RenderPlan`

```python
class RenderScene(BaseModel):
    position: int
    image_path: Path
    audio_path: Path
    audio_trim: tuple[float, float]
    duration_s: float              # durasi audio setelah trim + jeda
    motion: Motion                 # zoom_in / zoom_out / pan_left / pan_right / static / punch_in
    transition_in: Transition      # cut / crossfade
    words: list[WordTiming]        # sudah digeser ke waktu global

class RenderPlan(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    scenes: list[RenderScene]
    subtitle: SubtitleStyle
    bgm: BgmSettings | None
    output: OutputSettings
```

`build_render_plan(project, render_settings) -> RenderPlan` dan `build_ffmpeg_command(plan, paths) -> list[str]` adalah fungsi murni dan dites dengan snapshot.

### 8.2 Timeline

- Durasi scene = durasi clip setelah trim + jeda `0,08` detik. Scene terakhir mendapat tambahan `0,4` detik.
- SFX (Fase 6c): scene ke-2 dan seterusnya yang punya `transition_sfx` dengan file menambah `0,25` detik hening di akhir scene sebelumnya. SFX transisi mulai saat suara scene sebelumnya selesai, jadi diputar di jendela tanpa narasi sekitar `0,33` detik. SFX event mulai `0,15` detik sebelum kata pemicu (dicocokkan tanpa tanda baca dan huruf besar; tidak ketemu berarti kata pertama scene), tidak pernah sebelum awal scene. Cue yang mulai kurang dari `0,4` detik setelah cue sebelumnya dibuang, sehingga SFX transisi menang atas SFX event di awal scene yang sama.
- Batas scene dihitung dari jumlah kumulatif lalu dibulatkan ke bingkai (`int(t * 30 + 0,5)`), supaya selisih pembulatan tidak menumpuk.
- Waktu kata digeser ke waktu global dengan offset kumulatif dikurangi `trim.start`.

### 8.3 Gerak

- Gambar diskalakan ke lebar 2160 sebelum `zoompan` supaya gerakan halus tanpa getar.
- `zoom_in` / `zoom_out`: 1,00 ↔ 1,08 sepanjang scene. `pan_left` / `pan_right`: geser 6% lebar. `punch_in`: 1,00 → 1,06 dalam 0,2 detik pertama, lalu diam. `static`: tanpa gerak.
- Pemilihan: `diagram` → `static` atau zoom 1,00 → 1,03 supaya teks tetap terbaca. `closeup` → `punch_in`. Jenis lain → dipilih dari `hash(scene.id)`, dengan syarat tidak sama dengan scene sebelumnya. Hasilnya deterministik untuk render ulang.

### 8.4 Transisi

`cut` adalah default. `crossfade` memakai `xfade=transition=fade` selama 8 bingkai (0,267 detik), dipusatkan di batas scene (4 bingkai ke tiap sisi) sehingga gambar baru penuh tepat saat narasi mulai dan panjang total tetap sama dengan jumlah durasi scene. Crossfade menjadi `cut` bila scene pertama atau salah satu scene bersebelahan kurang dari 0,5 detik.

### 8.5 Subtitle

- Potongan subtitle (cue): 2 sampai 4 kata. Potong lebih awal pada tanda baca `. , ! ? ;`. Panjang maksimal 28 karakter per baris dan 940 piksel (diukur dengan font yang dibundel; yang lebih ketat menang), maksimal 2 baris.
- Teks dari `subtitle_override` bila ada, selain itu dari voiceover. Bila override dipakai, waktunya dibagi proporsional di dalam rentang scene.
- Gaya default (disimpan di `app_setting.subtitle_style`):
  - font Plus Jakarta Sans ExtraBold (OFL, dibundel di `app/assets/fonts/`), ukuran 78 px
  - putih dengan outline hitam 6 px, tanpa kotak latar
  - rata tengah, margin bawah 400 px (garis dasar y = 1520; Fase 11 menurunkannya dari 580 px / y = 1340 atas masukan pemilik — tetap di atas area tombol aplikasi)
  - kata di `emphasis_words` diberi warna sorot `#FFD84D` dan skala 110% lewat tag ASS `\c` dan `\fscx` / `\fscy`
- Dibakar dengan filter `ass` (libass) dan diekspor juga sebagai `.srt`.
- Watermark (Fase 6g): logo (dipotong persegi dari tengah lalu jadi lingkaran 72 px, `v` 2) dan teks (Plus Jakarta Sans ExtraBold 34 px, putih dengan outline hitam 3 px) digabung Pillow menjadi satu PNG transparan di folder kerja (`media/watermark.compose_watermark`), opacity dipasang di alpha. Setelah filter `ass`, PNG itu ditempel di kiri atas dengan margin 48 px (`overlay=48:48`), sebagai input terakhir setelah SFX. Tanpa watermark, graph sama persis dengan sebelumnya. Thumbnail buatan provider tidak diberi watermark; frame render (cadangan zip dan poster) diambil dari video, jadi ikut membawanya. Logo yang filenya hilang menggagalkan render dengan pesan yang menyebut halaman Sistem.

### 8.6 Audio

- Clip suara dipotong sesuai trim, dilengkapi hening sampai durasi scene (`apad=whole_dur`), lalu digabung.
- Musik latar opsional diulang sampai panjang video, volume dasar −22 dB, ducking dengan `sidechaincompress` dari jalur suara, fade-out 1 detik di akhir.
- SFX (Fase 6c): satu input per cue setelah musik, `volume` sesuai slot, `adelay` ke waktunya, digabung dengan `amix`, diisi hening sampai panjang video, lalu di-duck ringan oleh suara (`sidechaincompress` ratio 3, attack 5 ms) sebelum dicampur dengan suara dan musik. Tanpa cue, graph FFmpeg sama persis dengan sebelum Fase 6c. Render tanpa file SFX yang dipilih mencatat peringatan "SFX <nama> di scene <n> belum diunggah, dilewati."; pilihan yang slotnya sudah dihapus atau kategorinya lain dilewati dengan "SFX <nama> di scene <n> dilewati: tidak ada di pustaka." atau "... dilewati: bukan SFX event." (Fase 6f); file yang hilang dari penyimpanan menggagalkan render dengan pesan yang menyebut SFX-nya.
- Volume suara narasi (Fase 6f): `volume=<dB>dB` pada keluaran concat suara, sebelum ducking dan mix, hanya bila `app_setting.voice_volume_db` bukan 0. Manifest mendapat `voice_db` hanya bila bukan 0, jadi di 0 graph dan hash sama dengan sebelumnya. Karena master dinormalkan, angka ini mengatur keseimbangan narasi terhadap musik dan SFX. Mengubahnya membuat video usang tanpa render otomatis.
- `loudnorm=I=-14:TP=-1.5:LRA=11` di master.

### 8.7 Encode

- `h264_nvenc` dengan `-preset p5 -cq 21`. NVENC dideteksi lebih dulu dengan menyandikan satu bingkai uji (hasil di-cache per path FFmpeg). Bila tidak tersedia atau gagal, otomatis pakai `libx264 -preset medium -crf 20`; encoder yang dipakai dicatat di `render.encoder` dan log job. Hasil kosong atau lebih pendek 0,5 detik dari rencana ditolak.
- `-pix_fmt yuv420p -r 30`, AAC 192 kbps 48 kHz, `-movflags +faststart`.
- Thumbnail: frame pada detik 0,5 dari scene 1, JPEG kualitas 90. Sejak Fase 6b frame ini hanya cadangan di zip ekspor (dan poster pemutar); gambar thumbnail buatan (4.14) menggantikannya bila ada.
- Setelah render: verifikasi durasi dengan ffprobe. Di luar rentang target proyek (target_min_s/target_max_s) dicatat sebagai peringatan, tidak menggagalkan render (Fase 11 T10).

---

## 9. API

Prefix `/api`. Semua respons JSON kecuali file. Error memakai bentuk `{"error": {"kind", "message", "detail"}}`.

| Method | Path | Fungsi |
|---|---|---|
| GET | `/projects` | daftar project + ringkasan status |
| POST | `/projects` | buat project (`topic`, `category_id`, `format_id`) |
| GET | `/projects/{id}` | detail |
| PATCH | `/projects/{id}` | ubah pengaturan project (suara, provider, settings) |
| GET | `/projects/{id}/pipeline` | status tahap (4.13) |
| POST | `/projects/{id}/ideas/generate` | batch ide baru |
| GET | `/projects/{id}/ideas` | semua batch |
| POST | `/ideas/{id}/select` | Gerbang A |
| GET | `/projects/{id}/scripts` | daftar versi + skor |
| GET | `/scripts/{id}` | script + scene + hasil cek + validasi terakhir |
| POST | `/scripts/{id}/validate` | validasi ulang manual |
| POST | `/projects/{id}/script/generate` | script baru dari ide terpilih; juga dipakai saat belum ada script (menggantikan `POST /scripts/{id}/regenerate`) |
| POST | `/scripts/{id}/approve` | Gerbang B; body `{"claims_confirmed": bool}` |
| POST | `/scripts/{id}/scenes` | tambah scene |
| PATCH | `/scenes/{id}` | edit scene |
| DELETE | `/scenes/{id}` | hapus scene |
| POST | `/scripts/{id}/scenes/reorder` | urutkan ulang |
| GET | `/projects/{id}/production` | status suara dan gambar per scene |
| PATCH | `/projects/{id}` | suara, provider, gaya visual, `max_revisions`, `auto_render`, `bgm_enabled`, `sfx_enabled` |
| POST | `/scenes/{id}/voice/regenerate` | suara baru (`force`) |
| POST | `/scenes/{id}/image/regenerate` | gambar baru (`force`) |
| GET | `/scenes/{id}/assets` | semua versi aset scene |
| POST | `/assets/{id}/select` | pilih versi |
| POST | `/projects/{id}/regenerate-stale` | regenerate semua aset usang |
| POST | `/projects/{id}/render` | render manual (`force`); 409 `ScriptNotApproved`, `RenderNotReady`, `RenderUpToDate`; job aktif dikembalikan dengan `created=false` |
| GET | `/projects/{id}/renders` | riwayat render dengan keempat aset, `is_selected`, dan `stale` |
| PUT | `/projects/{id}/bgm` | unggah musik latar (badan mentah, audio, maksimal 20 MB, minimal 5 detik) |
| GET | `/sfx` | slot SFX, transisi dulu lalu event, masing-masing urut `created_at`: `name`, `category`, `description`, `volume_db`, `asset` |
| POST | `/sfx` | `{name, category, description}` → 201; 409 `SfxExists`; 422 `InvalidSfx` (nama, kategori, atau sudah 40 slot) |
| PUT | `/sfx/{name}` | unggah file ke slot (badan mentah, audio, maksimal 2 MB, 0,05 sampai 2 detik); 404 `NotFound` untuk nama lain. Tidak memicu render: video yang memakainya menjadi usang lewat `manifest_hash` |
| PATCH | `/sfx/{name}` | `{"volume_db"?, "description"?}` minimal satu; volume −30 sampai 0; kategori tidak bisa diubah |
| DELETE | `/sfx/{name}` | hapus slot (204); aset dan file tetap ada |
| GET, PATCH | `/settings/watermark` | `enabled`, `text`, `opacity_pct`, `logo`, plus batasnya; PATCH minimal satu field, 422 `InvalidWatermark` dengan pesan Indonesia |
| PUT, DELETE | `/settings/watermark/logo` | unggah logo (badan mentah PNG atau JPEG, maksimal 2 MB, transparansi dipertahankan, selalu aset baru) atau lepas logo (204, aset tetap ada) |
| GET | `/settings/watermark/preview.png` | PNG watermark dari pengaturan tersimpan; hanya kerja CPU, tanpa provider |
| GET, PUT | `/settings/voice-volume` | volume suara narasi global: `volume_db`, `min_db`, `max_db`, `step_db`; PUT `{"volume_db"}`, 422 `InvalidVolume` di luar −12..+6 atau bukan kelipatan 0,5 |
| GET | `/projects/{id}/metadata` | per platform: status, batas, versi terpilih, semua versi, job aktif, error terakhir |
| POST | `/projects/{id}/metadata/generate` | metadata baru (body opsional `platforms`); 409 `ScriptNotApproved`; job aktif dikembalikan dengan `created=false` |
| PATCH | `/metadata/{id}` | edit versi terpilih; 409 `MetadataNotSelected`, 422 `InvalidMetadata` |
| POST | `/metadata/{id}/select` | pilih versi |
| GET | `/projects/{id}/thumbnail` | status thumbnail: `state`, konsep terpilih dan semua versi, slot konsep dan gambar dengan `last_error`, semua versi gambar (4.14) |
| PATCH | `/thumbnail/concepts/{id}` | edit konsep terpilih (`title_text`, `visual_prompt`, `include_mascot`, minimal satu); 409 `ConceptNotSelected`, 422 `InvalidThumbnail` |
| POST | `/thumbnail/concepts/{id}/select` | pilih versi konsep lama |
| POST | `/projects/{id}/thumbnail/concept` | tulis ulang konsep lewat LLM (202); 409 `ScriptNotApproved`, `NoLlmProvider`; job aktif dikembalikan dengan `created=false` |
| POST | `/projects/{id}/thumbnail/image` | gambar baru dari konsep terpilih (202, tanpa body, selalu versi baru); 409 `ScriptNotApproved`, `NoThumbnailConcept`, `NoVisualStyle`, galat provider gambar |
| POST | `/thumbnail/images/{id}/select` | pilih versi gambar thumbnail |
| POST | `/projects/{id}/export` | buat zip (`force`); 409 `ScriptNotApproved`, `ExportNotReady`, `ExportUpToDate` |
| GET | `/projects/{id}/exports` | riwayat paket dengan `url`, `filename`, `files`, `warnings`, `is_selected`, `stale` |
| GET | `/projects/{id}/usage` | pemakaian per (kemampuan, provider, model) dengan `state` (`priced` / `unknown` / `free` / `dry_run`), biaya, total per mata uang, `unpriced_calls`, `complete` |
| GET | `/jobs/{id}` | detail job |
| GET | `/jobs/{id}/events` | log |
| POST | `/jobs/{id}/cancel` | batal |
| POST | `/jobs/{id}/retry` | coba lagi dengan input sama |
| GET | `/files/{key:path}` | sajikan aset dari Storage lokal |
| GET, POST | `/providers` | daftar, tambah |
| GET | `/providers/adapters` | adapter yang dikenal, `dry_run`, dan quirks bawaannya |
| POST | `/providers/reorder` | urutan satu kemampuan (prioritas jadi 10, 20, 30, ...); mengembalikan provider kemampuan itu saja |
| PATCH | `/providers/{id}` | nama, base URL (http/https), kunci baru atau `clear_api_key`, model bawaan, quirks, aktif, prioritas; semua divalidasi sebelum ada yang disimpan |
| DELETE | `/providers/{id}` | hapus (204); 409 `ProviderInUse` bila di-pin project, punya job aktif, atau punya catatan pemakaian |
| GET, PUT | `/providers/{id}/prices` | harga per model (PUT mengganti seluruh daftar), plus `unpriced_models` |
| POST | `/providers/{id}/test` | tes koneksi (job `provider_test`) |
| GET | `/providers/{id}/voices` | daftar suara |
| GET, PATCH | `/visual-styles`, `/visual-styles/{id}` | gaya visual |
| POST | `/visual-styles/{id}/reference` | unggah gambar referensi stickman |
| GET | `/categories`, `/formats` | daftar |
| GET | `/prompts`, `/prompts/{key}/versions` | baca prompt dan versinya |
| GET, PATCH | `/settings` | `app_setting` |

Respons provider tidak pernah memuat API key. Field yang dikembalikan adalah `has_api_key: bool` dan `api_key_hint` (4 karakter terakhir).

Rute yang ditambah sejak Fase 6 memakai `NotFoundError` (`domain/errors.py`) untuk record yang tidak ada: 404 `NotFound` dengan pesan Indonesia sendiri. `LookupError` polos dari kode lama tetap menjawab 404, tetapi dicatat sebagai peringatan dengan traceback. Uang di JSON selalu string desimal, tidak pernah float.

---

## 10. Keamanan

- `APP_SECRET_KEY` (kunci Fernet) wajib ada. API menolak start bila kosong.
- API key dienkripsi saat disimpan, didekripsi hanya di worker atau di proses tes koneksi, dan tidak pernah ditulis ke log. Logger memakai filter yang menyamarkan pola `sk-…`, `Bearer …`, dan nilai `xi-api-key`.
- Localhost: API hanya bind ke `127.0.0.1`. CORS hanya untuk origin Vite (`localhost:5180`). Port 8010 dan 5180 dipilih supaya v1 (8000, 5173) bisa tetap berjalan bersamaan.
- VPS: login dengan password tunggal (`APP_PASSWORD_HASH`, argon2), cookie sesi HttpOnly + SameSite=Lax, HTTPS lewat Caddy.
- Perubahan provider dan pengaturan dicatat di `audit_event` tanpa nilai rahasia. Ditunda: tabel `audit_event` belum dibuat; sampai Fase 7, buat, ubah (hanya nama kolom yang berubah), urut ulang, dan hapus provider dicatat sebagai log INFO tanpa nilai rahasia. Kunci baru langsung didaftarkan ke penyamar log saat disimpan.
- `GET /files` hanya melayani key di bawah root Storage. Path traversal ditolak.
- `base_url` provider boleh menunjuk ke localhost karena relay pemilik berjalan lokal. Aplikasi hanya dipakai satu orang tepercaya.

---

## 11. Konfigurasi (`.env`)

| Variabel | Default | Fungsi |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./storage/app.db` | |
| `APP_SECRET_KEY` | wajib | kunci Fernet |
| `STORAGE_BACKEND` | `local` | |
| `STORAGE_PATH` | `./storage` | |
| `FFMPEG_PATH`, `FFPROBE_PATH` | `ffmpeg`, `ffprobe` | |
| `WHISPER_MODEL` | `small` | |
| `WHISPER_DEVICE` | `auto` | `cuda` / `cpu` / `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` | |
| `WORKER_CONCURRENCY` | `6` | |
| `LOG_LEVEL` | `INFO` | |
| `SEED_LLM_BASE_URL`, `SEED_LLM_API_KEY`, `SEED_LLM_MODEL` | kosong | seed provider saat DB kosong |
| `SEED_IMAGE_BASE_URL`, `SEED_IMAGE_API_KEY`, `SEED_IMAGE_MODEL` | kosong | |
| `SEED_ELEVENLABS_API_KEY`, `SEED_ELEVENLABS_VOICE_ID` | kosong | |
| `SEED_GEMINI_TTS_VOICE` | kosong | suara bawaan Gemini TTS (default `Aoede`) |
| `FFMPEG_PATH`, `FFPROBE_PATH` | `ffmpeg`, `ffprobe` | |
| `SEED_GEMINI_TTS_URL`, `SEED_GEMINI_TTS_API_KEY`, `SEED_GEMINI_TTS_MODEL` | kosong | |
| `SEED_AISTUDIO_TTS_URL`, `SEED_AISTUDIO_TTS_API_KEY`, `SEED_AISTUDIO_TTS_VOICE` | kosong | provider AI Studio TTS, sekali (marker `seed.voice.aistudio`) |

Variabel `SEED_*` dipakai sekali per kemampuan: provider dibuat bila `app_setting["seed.providers"]` belum mencatat kemampuan itu, lalu kemampuan itu dicatat. Provider yang kemudian dihapus atau diubah pengguna tidak dibuat ulang. Setelah itu sumber kebenarannya adalah DB. Saat router LLM di-seed, provider Fake LLM dinonaktifkan supaya ide palsu tidak pernah menjadi cadangan; untuk dry-run, aktifkan lagi lewat `PATCH /providers/{id}`.

---

## 12. Pengujian

| Lapisan | Alat | Cakupan |
|---|---|---|
| Unit | pytest | cek otomatis, repair JSON, `input_hash`, pencocokan alignment, pemotongan cue subtitle, builder ASS dan SRT, pemilihan gerak, `reconcile`, kalkulasi status pipeline, perhitungan biaya |
| Snapshot | pytest | `build_ffmpeg_command`, render prompt bawaan, `output_contract` |
| Kontrak adapter | pytest + respx | setiap adapter terhadap respons HTTP rekaman, termasuk pemetaan error |
| Integrasi | pytest, SQLite sementara, Storage sementara, provider `fake`, FFmpeg asli | dari project baru sampai zip, termasuk regenerate satu scene dan pemulihan setelah worker dihentikan paksa |
| Frontend | vitest + Testing Library | komponen editor scene, tampilan status pipeline |

Tes integrasi dengan FFmpeg asli memakai gambar dan audio `fake` berukuran kecil, sehingga selesai dalam hitungan detik.

---

## 13. Porting dari v1

| Dari `ai-conten-creator` | Ke | Perubahan |
|---|---|---|
| `llm.py`: `_parse_json`, `_strip_trailing_commas`, logika retry kontrak | `services/structured_llm.py` | dipisah dari pemanggilan provider |
| `llm_contract.py`: `fix_invalid_json_escapes` | `services/json_repair.py` | |
| `tts.py`: parser alignment karakter ElevenLabs, `sanitize_tts_text`, `words_to_srt` | `providers/voice/elevenlabs.py`, `pipeline/voice.py`, `render/srt.py` | |
| `tts.py`: payload Gemini TTS | `providers/voice/openai_compatible.py` + quirks | tidak ada lagi URL yang ditulis di kode |
| `image.py`: sanitasi `base_url`, unduh URL, fallback tanpa `size` | `providers/image/openai_compatible.py` | fallback `size` digantikan quirk `accepts_size` |
| `image.py`: teks zona aman dan teks berbahasa Indonesia | `prompts/blocks/safe_zone.md` | |
| `short_common.py`, `short_script.py`, `short_validation.py`: isi aturan prompt | `prompts/tasks/*`, `prompts/blocks/*` | ditulis ulang untuk stickman berkepala hijau dan schema baru |
| `ffmpeg.py` | `render/` | dirombak menjadi builder murni + runner |

Mode comic, mode long, dan `aistudio_job` tidak di-port di MVP.

---

## 14. Fase implementasi

| Fase | Isi | Selesai bila |
|---|---|---|
| 0 | Spike dukungan gambar referensi di relay (hasil: tidak didukung). Penyusunan DESIGN.md untuk UI bersama pemilik. | `supports_reference_image` diketahui, DESIGN.md disetujui |
| 1 | Repo backend dan frontend, config, DB + Alembic, Storage lokal, antrean + worker + heartbeat, `reconcile` kerangka, registry + provider `fake`, `dev.ps1`, CLAUDE.md | Job `fake` berjalan dari antrean sampai selesai dan tampil di halaman sederhana |
| 2 | `PromptService`, `StructuredLLM`, adapter LLM, Kategori dan Format, seed provider, UI buat project + pilih ide | Topik sungguhan menghasilkan 8 ide di UI |
| 3 | Script, cek otomatis, validasi, revisi, editor scene | Script tervalidasi bisa diedit dan disetujui |
| 4 | Adapter suara, alignment, adapter gambar, Visual Style, grid scene dengan regenerate dan versi | Semua scene punya suara, timing, dan gambar |
| 5 | Render lengkap dan preview | MP4 9:16 bisa diputar dengan subtitle sinkron |
| 6 | Metadata, export, tampilan biaya, UI Settings provider. Selesai (branch `fase-6-metadata-export`): migrasi 0007, tab Metadata dan Ekspor, harga dan biaya dihitung saat dibaca, kelola provider di halaman Sistem | MVP selesai ujung ke ujung |
| 6b | Thumbnail terpisah: konsep (teks + prompt) ditulis LLM setelah script disetujui, gambar 9:16 dengan teks judul dibuat sesudahnya, keduanya otomatis hanya sekali; edit, versi, dan buat ulang atas klik; zip ekspor memakai gambar ini sebagai `thumbnail.jpg`. Selesai (branch `fase-6b-thumbnail`): migrasi 0008, kartu Thumbnail di tab Produksi, baris syarat di tab Ekspor | Zip berisi `thumbnail.jpg` 1080x1920 dari gambar thumbnail |
| 6s | Mode Video AI: opsi per project (`settings.visual_mode`: `image` vs `video`), capability video baru, adapter `openai_compatible` ke relay `/v1/videos/generations` (Omni Flash 1.1), pemotongan durasi video di FFmpeg mengikuti narasi audio, thumbnail tetap lewat provider gambar. Rencana: `docs/plans/2026-10-15-fase-6s-mode-video-ai.md` | Proyek mode video menghasilkan klip video AI per scene dan me-render video MP4 final dengan durasi dan subtitle sinkron |
| 7 | Login, docker compose, migrasi Postgres, backup, rotasi log | Berjalan di VPS |

Setiap fase mendapat rencana implementasi sendiri.
