# Fase 1 — Kerangka Berjalan (Walking Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Job `fake` berjalan dari antrean sampai selesai dan tampil di halaman sederhana (kriteria selesai Fase 1, Spec.md §14).

**Architecture:** Monorepo sesuai Spec §1.2: backend FastAPI + worker asyncio berbagi satu DB SQLite (WAL) sebagai antrean job; frontend React SPA mem-poll API. Lapisan `api` hanya memanggil `services`/`jobs.enqueue`; provider hanya dikenal lewat registry `ADAPTERS`.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2 async + Alembic, aiosqlite, Pydantic v2 + pydantic-settings, httpx, Pillow, cryptography · React 18, Vite, TypeScript, TanStack Query, Vitest · pytest, pytest-asyncio, respx.

**Spec:** `Spec.md` (di root repo) — terutama §1.2, §1.3, §2.3 (`generation_job`, `job_event`, `usage_record`), §5.6 (provider fake), §7 (sistem job), §9 (API), §10 (keamanan), §14 Fase 1. Penyesuaian provider Muse ada di `ADJUSTMENTS.md` dan masuk mulai Fase 2; Fase 1 murni `fake`.

## Global Constraints

- ID memakai ULID (string 26 karakter, terurut waktu); semua waktu UTC.
- Prefix API `/api`; error selalu berbentuk `{"error": {"kind", "message", "detail"}}`; pesan error untuk pengguna berbahasa Indonesia.
- API bind `127.0.0.1:8010`; web dev di port `5180` dengan proxy `/api` → `8010`.
- `APP_SECRET_KEY` wajib ada; API menolak start bila kosong.
- DB lokal: file SQLite `backend/storage/app.db` mode WAL; `DATABASE_URL` default `sqlite+aiosqlite:///./storage/app.db`.
- Job demo Fase 1 hanya `provider_test` (Spec §2.3) memakai provider `fake`; tipe lain → 422 `UnsupportedJobType`.
- Unique index parsial job aktif: `(type, project_id, scene_id, input_hash)` di mana `status IN ('queued','processing')`.
- Komentar kode seperlunya dan berisi informasi nyata (antislop-code); tanpa komentar dekoratif/restating.

## Review Focus

- `APP_SECRET_KEY` kosong atau hilang → API/worker menolak start dengan pesan jelas, bukan jalan tanpa rahasia. (Task 1)
- Dua enqueue identik yang masih aktif → yang kedua ditolak/dedup oleh unique index, bukan dua job berjalan. (Task 2)
- Worker mati saat job `processing` → heartbeat basi >60 dtk membuat job kembali `queued` (percobaan tersisa) atau `failed` `WorkerInterrupted`. (Task 3)
- Kunci storage mengandung `../` → ditolak, file tidak pernah keluar dari root storage. (Task 2)
- Body enqueue tidak valid / tipe tak didukung → 422 dalam bentuk error standar, tidak pernah 500. (Task 4)

## File Structure

```text
backend/
├── pyproject.toml            deps + konfigurasi ruff/pyright/pytest
├── alembic.ini, alembic/     env async + migrasi 0001 (job, job_event, usage)
├── app/
│   ├── main.py               factory `serve()` + handler error standar
│   ├── worker.py             entrypoint `python -m app.worker`
│   ├── config.py             Settings (pydantic-settings)
│   ├── ids.py                generator ULID
│   ├── api/jobs.py           rute /api/jobs*, /api/health
│   ├── db/models.py          GenerationJob, JobEvent, UsageRecord
│   ├── db/session.py         engine, session factory, WAL
│   ├── jobs/queue.py         enqueue, claim, complete, fail, recover_stale
│   ├── jobs/context.py       CallContext: progress + log ke DB
│   ├── jobs/handlers.py      HANDLERS = {"provider_test": ...}
│   ├── providers/base.py     Protocol + caps minimal
│   ├── providers/registry.py ADAPTERS (fake saja di Fase 1)
│   ├── providers/llm/fake.py, voice/fake.py, image/fake.py, video/fake.py
│   ├── services/reconcile.py kerangka: catat log, tanpa aksi (Fase 2 mengisi)
│   └── storage/base.py, local.py
└── tests/                    test_ids, test_config, test_queue, test_storage,
                              test_worker, test_api
frontend/
├── package.json, vite.config.ts (port 5180, proxy /api), index.html
└── src/main.tsx, App.tsx, lib/jobs.ts, lib/jobs.test.ts, styles.css
dev.ps1 (uv + pnpm, Windows pemilik), dev.sh (venv + pnpm/npm, VM ini)
CLAUDE.md, .gitignore, .superpowers/sdd/fase-1-kerangka/progress.md (ledger)
```

---

### Task 1: Scaffold backend, config, ULID

**Files:**
- Create: `backend/pyproject.toml`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/ids.py`
- Test: `backend/tests/test_ids.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces: `new_ulid() -> str` (26 char Crockford Base32, awalan waktu ms); `Settings` dengan field `app_secret_key: str` (wajib), `database_url`, `storage_path: Path`, `worker_concurrency: int = 6`, `log_level: str = "INFO"`; `get_settings() -> Settings`.

- [ ] **Step 1: Write the failing tests** — `test_ids`: panjang 26, hanya alfabet Crockford, dua panggilan berbeda, id dari ms lebih baru > id lebih lama. `test_config`: tanpa `APP_SECRET_KEY` → `ValidationError`; dengan env → field terbaca, default `database_url` persis seperti Global Constraints.
- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_ids.py tests/test_config.py -q` → Expected: FAIL (modul belum ada).
- [ ] **Step 3: Implement** `ids.py` (timestamp 48-bit + 80-bit acak `os.urandom`, encode Crockford) dan `config.py` (`BaseSettings`, `model_config` env_file `.env`).
- [ ] **Step 4: Run** tes yang sama → Expected: PASS.
- [ ] **Step 5: Commit** `feat(fase-1): scaffold backend, config, dan ULID`

### Task 2: Model DB, migrasi, storage lokal, antrean

**Files:**
- Create: `backend/app/db/models.py`, `backend/app/db/session.py`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_job_tables.py`, `backend/app/storage/base.py`, `backend/app/storage/local.py`, `backend/app/jobs/__init__.py`, `backend/app/jobs/queue.py`
- Test: `backend/tests/test_queue.py`, `backend/tests/test_storage.py`

**Interfaces:**
- Consumes: `new_ulid`, `Settings`.
- Produces: `GenerationJob` (kolom Spec §2.3 subset Fase 1: id, type, project_id, scene_id, parent_id, status, resource_key, input, input_hash, result, error, attempts, max_attempts, priority, run_after, locked_by, heartbeat_at, cancel_requested, progress, progress_message, prompt_version_id, provider_id, model, created_at, started_at, finished_at), `JobEvent`, `UsageRecord`; `sha256_of_json(obj) -> str` (JSON kanonis kunci terurut tanpa spasi); `enqueue(session, *, type, input, resource_key="local", priority=100, max_attempts=3) -> GenerationJob` (mengisi `input_hash`); `claim_next(session, *, worker_id, full_keys) -> GenerationJob | None` (SQL Spec §7.1 versi SQLite); `LocalStorage(root)` dengan `put/open/local_path/delete` dan penolakan traversal.

- [ ] **Step 1: Write the failing tests** — antrean: klaim mengambil prioritas terkecil lalu FIFO; job belum `run_after` tidak terambil; `resource_key` yang penuh tidak terambil; enqueue duplikat aktif melanggar unique index (`IntegrityError`). Storage: put→open roundtrip byte sama; `local_path("../x")` → `ValueError`.
- [ ] **Step 2: Run** → Expected: FAIL.
- [ ] **Step 3: Implement** model + migrasi 0001 (termasuk unique index parsial `sqlite_where`/`postgresql_where`), session WAL (`PRAGMA journal_mode=WAL` saat connect), queue, storage.
- [ ] **Step 4: Run** → Expected: PASS. Lalu `alembic upgrade head` pada DB sementara → Expected: tiga tabel terbentuk.
- [ ] **Step 5: Commit** `feat(fase-1): model job, storage lokal, dan antrean`

### Task 3: Provider fake, handler, worker

**Files:**
- Create: `backend/app/providers/base.py`, `backend/app/providers/registry.py`, `backend/app/providers/llm/fake.py`, `backend/app/providers/voice/fake.py`, `backend/app/providers/image/fake.py`, `backend/app/providers/video/fake.py`, `backend/app/jobs/context.py`, `backend/app/jobs/handlers.py`, `backend/app/services/reconcile.py`, `backend/app/worker.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: queue Task 2.
- Produces: `ADAPTERS: dict[tuple[str, str], type]` berisi `("llm","fake")`, `("voice","fake")`, `("image","fake")`, `("video","fake")`; `FakeLLM.generate_text(req, ctx) -> TextResult` (JSON minimal valid dari schema bila diminta, selain itu `{"ok": true}`); `run_provider_test(job, ctx)` — panggil FakeLLM, update progress 50→100, tulis `usage_record` (capability `llm`, provider fake); `Worker.run()` — loop klaim tiap 1 dtk, heartbeat ticker 10 dtk, `recover_stale()` saat start & tiap 30 dtk (Spec §7.4); `reconcile(project_id: str | None)` kerangka (log saja).

- [ ] **Step 1: Write the failing tests** — registry memuat 4 adapter fake; worker pada DB sementara: enqueue `provider_test` → dalam 5 dtk status `completed`, `result` memuat keluaran fake, ada `job_event` dan satu `usage_record`; job `processing` basi (heartbeat 120 dtk lalu, attempts 1/3) → `recover_stale` mengembalikannya ke `queued`; attempts habis → `failed` dengan `error.kind == "WorkerInterrupted"`.
- [ ] **Step 2: Run** → Expected: FAIL.
- [ ] **Step 3: Implement** base/registry/fake, context (progress menulis DB maks 1×/dtk per job), handlers, worker, reconcile kerangka.
- [ ] **Step 4: Run** → Expected: PASS.
- [ ] **Step 5: Commit** `feat(fase-1): provider fake dan worker`

### Task 4: API + skrip dev

**Files:**
- Create: `backend/app/main.py`, `backend/app/api/__init__.py`, `backend/app/api/jobs.py`, `dev.ps1`, `dev.sh`, `CLAUDE.md`, `.gitignore`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `enqueue`, model Task 2.
- Produces: `serve() -> FastAPI`; `GET /api/health` → `{"status": "ok"}`; `POST /api/jobs` body `{"type": "provider_test", "input": {...}}` → 202 representasi job; `GET /api/jobs` (terbaru dulu, `limit` default 50); `GET /api/jobs/{id}`; `GET /api/jobs/{id}/events`; `POST /api/jobs/{id}/cancel` (queued → `cancelled`); error handler global → bentuk standar (404 `NotFound`, 422 `ValidationError`/`UnsupportedJobType`).

- [ ] **Step 1: Write the failing tests** (fastapi `TestClient`, DB sementara) — health ok; enqueue 202 lalu GET menampilkan `status == "queued"`; tipe `script` → 422 `error.kind == "UnsupportedJobType"`; id tidak ada → 404 `error.kind == "NotFound"`; cancel job queued → `cancelled`.
- [ ] **Step 2: Run** → Expected: FAIL.
- [ ] **Step 3: Implement** main + api + handler error; `dev.ps1` (uv run uvicorn, uv run python -m app.worker, pnpm dev) dan `dev.sh` (venv `.venv` + pip, pnpm bila ada selain npm); `CLAUDE.md` berisi arsitektur singkat + perintah jalan/tes.
- [ ] **Step 4: Run** seluruh suite backend → Expected: PASS semua.
- [ ] **Step 5: Commit** `feat(fase-1): API job dan skrip dev`

### Task 5: Frontend + verifikasi ujung-ke-ujung

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/lib/jobs.ts`, `frontend/src/lib/jobs.test.ts`, `frontend/src/styles.css`, `frontend/.gitignore`

**Interfaces:**
- Consumes: API Task 4.
- Produces: `statusLabel(status: string) -> string` (queued→"Antre", processing→"Berjalan", completed→"Selesai", failed→"Gagal", cancelled→"Dibatalkan"); halaman `/`: judul produk, form enqueue job contoh (label teks bebas), tabel job (status, tipe, progres, dibuat) dengan polling TanStack Query 1 dtk. Identitas visual dari produk (antislop-ui): kertas off-white hangat, tinta hitam, aksen hijau maskot hanya pada aksi utama & status selesai; tanpa gradasi, tanpa glass, tanpa grid latar.

- [ ] **Step 1: Write the failing test** — vitest: `statusLabel` memetakan kelimanya, status tak dikenal dikembalikan apa adanya.
- [ ] **Step 2: Run** `cd frontend && pnpm vitest run` → Expected: FAIL (modul belum ada).
- [ ] **Step 3: Implement** jobs.ts + App + styles + config (proxy `/api` → `http://127.0.0.1:8010`).
- [ ] **Step 4: Run** vitest → PASS; `pnpm build` → exit 0.
- [ ] **Step 5: E2E nyata** — `alembic upgrade head` (DB baru), jalankan worker + API, `POST /api/jobs` dari curl, poll `GET /api/jobs/{id}` sampai `completed`, jalankan `pnpm dev` dan curl halaman (200 + judul). Catat buktinya di ledger.
- [ ] **Step 6: Commit** `feat(fase-1): frontend antrean job + e2e kerangka berjalan`
