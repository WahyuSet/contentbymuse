# Fase 8 — Tahap Publish (YouTube Shorts + Facebook Reels, full auto)

Keputusan pemilik (2026-10-22): publish FULL AUTO begitu paket lengkap;
YouTube Shorts via browser (login channel sekali di browser Muse);
Facebook ke Page khusus. Upload beneran dijalankan agen (Muse) lewat
browser — worker pabrik tidak bisa mengemudikan browser — jadi fase ini
dibagi dua: pabrik menyiapkan antrean + paket yang tervalidasi, agen
mengeksekusi upload dan melapor balik lewat API.

## Model (migrasi 0007)

`publish_record`: id, project_id, render_id, platform ("youtube"|"facebook"),
status ("queued"|"awaiting_upload"|"uploading"|"published"|"failed"),
external_id, url, error, attempts, created_at, updated_at.
Unik per (project_id, render_id, platform) — render baru = rekor baru.

## Job publish

Reconcile `_reconcile_publish` (sesudah extras): bila render terpilih +
thumbnail terpilih + metadata terpilih ada DAN metadata cocok dengan render
dan script aktif (data.render_id == render.id, data.script_id ==
project.active_script_id — gerbang dari review Fase 7), buat PublishRecord
per platform (queued) dan antrekan job `publish` (enqueue_once,
input {"publish_id": ...}).

Handler `run_publish`: muat rekor; validasi paket (berkas video render ada —
render asset data.files.video — berkas thumbnail ada, metadata cocok);
rakit manifest JSON ke storage `publish/<record_id>/manifest.json`
{platform, video_path, thumbnail_path, title, description, hashtags,
fb_caption}; rekor -> awaiting_upload. Validasi gagal: rekor failed +
alasan, job error non-retryable. Idempoten: rekor yang sudah
awaiting/published tidak dirakit ulang.

## API

- `GET /projects/{id}/publish` -> daftar rekor project (platform, status, url, error).
- `GET /publish/awaiting` -> rekor berstatus awaiting_upload + isi manifest
  (untuk eksekutor agen).
- `POST /publish/{record_id}/claim` -> awaiting_upload -> uploading
  (409 bila bukan awaiting).
- `POST /publish/{record_id}/result` {status: "published"|"failed", url?,
  external_id?, error?} -> perbarui rekor dari uploading/awaiting.

## UI

PublishPanel di halaman project: status per platform + tautan bila sudah
published + pesan error bila gagal.

## Di luar pabrik (go-live, langkah terpisah sesudah build)

- Eksekutor agen: cron berkala memeriksa GET /publish/awaiting, claim,
  upload via browser (YouTube Studio; FB Page), lapor via /result.
  Prasyarat: login channel YouTube sekali + Page FB tersedia.
- Penjadwalan produksi harian (riset berita -> produksi -> publish)
  sebagai cron agen terpisah.
