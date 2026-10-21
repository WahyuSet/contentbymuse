# Fase 7 — Video Utuh: SFX, Thumbnail AI, Metadata

Keputusan pemilik (2026-10-22): thumbnail digambar seluruhnya oleh AI (teks judul
di dalam prompt, Bahasa Indonesia); Facebook tujuan publish = Page khusus;
mode automasi = full auto (Fase 8). Fase ini menyiapkan tiga keluaran yang
Fase 8 butuhkan: video dengan SFX, thumbnail, metadata.

## Task 1 — Perpustakaan SFX

- `backend/scripts/build_sfx_library.py`: sintesis 9 efek lisensi-bersih dengan
  FFmpeg ke `backend/app/assets/sfx/<id>.wav` (44.1kHz mono): ding, boom,
  whoosh, pop, cash (denting koin), fall (slide turun), drum (sting pendek),
  scratch, sparkle. Deterministik; file ikut repo.
- `app/services/sfx_catalog.py`: katalog id → {nama Indonesia, berkas, gain
  bawaan, durasi}; `sfx_path(id)`, `is_valid_sfx(id)`.

## Task 2 — Cue SFX pada scene

- Migrasi 0006: `scene.sfx_cues` JSON default `[]`; elemen
  `{"sfx": "<id>", "word": "<kata pemicu>", "gain": 0.0–1.0 opsional}`.
- API: SceneOut/ScenePatch/SceneCreate mengekspos `sfx_cues`; validasi id SFX
  (422 `InvalidSfx` untuk id tak dikenal).
- Prompt: blok `blocks/sfx_rules.md` masuk script.generate/fix/revise —
  maksimal 2 cue per scene, hanya pada kata yang benar-benar ada di narasi,
  pilih dari katalog. Skema ScriptDraft scene mendapat field `sfx_cues`
  (opsional, default kosong) dan handler script menyimpannya.

## Task 3 — Render mencampur SFX

- `build_render_plan`: event SFX global dari cue — waktu = awal kata pemicu
  pada timing global scene (kata tak ditemukan → awal scene); event transisi
  `whoosh` gain rendah pada setiap awal scene selain scene pertama.
- `build_ffmpeg_command`: setiap event menjadi input tambahan; rantai
  `atrim` seperlunya + `adelay` + `volume`, semua event + rantai suara
  digabung `amix=inputs=N:normalize=0` sebelum loudnorm. Tanpa event, graf
  identik dengan sebelumnya.
- Hash render memasukkan `sfx_cues` per scene.

## Task 4 — Thumbnail AI

- Job `thumbnail`: untuk project dengan render terpilih; prompt konsep dari
  hook script + gaya visual + teks judul pendek persis (Bahasa Indonesia)
  yang digambar AI; provider gambar yang sama seperti scene (CLI Muse);
  normalisasi 1080×1920; aset kind `thumbnail` terpilih per project.
- Reconcile mengantrekan thumbnail setelah render tersedia dan belum ada
  thumbnail untuk hash render itu. API `GET /projects/{id}/thumbnail`.

## Task 5 — Metadata

- Prompt `metadata.generate` (StructuredLLM + fixture FakeLLM): dari judul
  project + naskah menghasilkan `{title, description, hashtags, fb_caption}`.
- Job `metadata` menyimpan aset kind `metadata` (data JSON + berkas JSON di
  storage). Reconcile setelah render; API `GET /projects/{id}/metadata`.
- UI: RenderPanel menampilkan thumbnail + judul/deskripsi metadata.

## Verifikasi

Tes unit per task; E2E pada project MSCI: antre ulang render (hash berubah
karena cue) → dengar/lihat SFX tercampur (durasi sama, LUFS wajar), thumbnail
terbentuk, metadata terbentuk. Review menyeluruh seperti fase sebelumnya.
