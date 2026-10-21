# Stickman Content Factory

Pabrik konten Shorts stickman berkepala hijau (watermark `@SiKlepon-id`).
Spec teknis lengkap: `Spec.md`. Penyesuaian provider Muse: `ADJUSTMENTS.md`.
Rencana per fase: `docs/plans/`.

## Arsitektur (ringkas)

- `backend/` FastAPI (hanya validasi + baca/tulis DB + enqueue job) dan worker
  asyncio yang menjalankan pipeline lewat `ProviderRouter` → adapter.
  Nama vendor hanya muncul di `backend/app/providers/` dan registry `ADAPTERS`.
- `frontend/` React 18 + Vite + TypeScript, polling REST ke `/api`.
- DB adalah antrean job: SQLite (WAL) lokal, Postgres di VPS. ID = ULID, waktu UTC.
- Aset tidak pernah ditimpa; status usang selalu dihitung dari `input_hash`.

## Menjalankan

- Windows: `dev.ps1` (uv + pnpm). VM Linux ini: `bash dev.sh` (venv + pnpm/npm).
- API `127.0.0.1:8010`, web `localhost:5180` (proxy `/api` → 8010).
- `backend/.env` wajib berisi `APP_SECRET_KEY` (lihat `backend/.env.example`).

## Tes

- Backend: `cd backend && .venv/bin/python -m pytest` (di Windows: `uv run pytest`).
- Frontend: `cd frontend && pnpm vitest run && pnpm build`.

## Konvensi

- Pesan error untuk pengguna dan teks UI berbahasa Indonesia.
- Komentar kode hanya yang membawa informasi nyata; tanpa komentar dekoratif.
