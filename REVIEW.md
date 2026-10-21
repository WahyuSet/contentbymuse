# Review Teknis — Stickman Content Factory (`Spec.md`)

- **Tanggal review:** 2026-10-21 (~11:15 WIB)
- **Reviewer:** Muse
- **Target:** `~/workspace/stickman/Spec.md` — 1.144 baris, 14 bagian, status "Draf untuk review" (header bertanggal 2026-10-07)
- **Batasan:** PRD yang direferensikan (`../PRD.md`) dan repo-nya tidak ada di workspace — review ini murni dari spec teknisnya, belum disilang ke PRD.

## Verdict

Ini bukan spec asal-asalan — salah satu spec paling mateng yang pernah dilempar ke meja ini. Jauh lebih serius dari pilot Bang Mullet di chat sebelah; ini pabriknya beneran.

## Yang paling kuat

1. **Idempoten di mana-mana.** `job_id` nempel di baris hasil generate, `input_hash` buat cache + dedup, `enqueue_once`, handler yang di-retry setelah worker mati memakai baris yang sama bukan bikin duplikat. Ini yang biasanya spec lain lupa total.
2. **Status usang dihitung, bukan disimpan** — dari `input_hash` dan `manifest_hash`. Nggak bakal ada flag stale bohong.
3. **Versi tidak pernah diubah** — script, metadata, thumbnail, prompt, aset. Edit selalu bikin versi baru. Audit-nya gampang.
4. **Validator LLM dikekang bukti** di Fase 6o: issue wajib bawa kutipan kata per kata, kutipan yang nggak terbukti diturunkan severity-nya oleh kode. Itu obat anti-halusinasi yang bener.

## 6 lubang yang harus diberesin sebelum spec dianggap final

### 1. Status dokumennya membingungkan
Header bilang "Draf untuk review, 2026-10-07", tapi isinya udah termasuk Fase 6b–6r yang ditandai *selesai* di branch, plus rencana 6s bertanggal 2026-10-15. Jadi ini as-built atau to-build? Orang yang bangun dari nol nggak bisa bedain mana MVP, mana yang udah jadi, mana NICE TO HAVE. **Perlu tanggal diperbarui + penanda status per fase.**

### 2. Fase 6s (mode video) belum menyatu ke spec inti
Capability `video`, adapter, job `video`, dan aset `scene_video` udah ada — tapi:
- di 5.1 nggak ada protocol `VideoProvider` (cuma LLM/Voice/Image/Storage/Aligner/Renderer),
- nggak ada model `VideoRequest`/`VideoResult`,
- `RenderPlan` di 8.1 masih cuma punya `image_path`,
- `reconcile` di 4.12 + status pipeline di 4.13 masih cuma ngurus tahap `image`.

6s sekarang kayak ditempel — belum ditulis ulang ke 4.12, 4.13, 5.1, dan 8.

### 3. Jebakan NULL di unique index
Janji "satu `is_selected` per `(project, scene, kind)`" dan dedup job `(type, project, scene, input_hash)` runtuh justru buat aset/job tingkat project — `render`, `metadata`, `thumbnail_image`, `bgm` — karena `scene_id`-nya NULL, dan SQLite maupun Postgres nganggep NULL itu selalu beda di unique index. Jaminannya hilang di tempat yang paling butuh. **Solusi:** index ekspresi `COALESCE(scene_id, '')` atau kolom sentinel. Sekalian: enum job di 2.3 belum ada `scene_split` yang dipakai di 4.5, tapi masih nyimpen `voice_batch`/`image_batch` yang katanya nggak pernah dibuat.

### 4. Kontradiksi aset berbayar + nggak ada rem biaya
Pseudocode 4.12 bilang begitu script disetujui, voice + image semua scene otomatis di-enqueue — itu panggilan berbayar. Tapi paragraf penutupnya bilang "aset berbayar tetap menunggu pengguna". **Salah satu harus dicoret.** Dan di seluruh spec nggak ada budget cap per project: loop revisi + retry + regenerate bisa ngabisin kuota ElevenLabs/relay tanpa batas, biaya cuma *dilaporkan* saat dibaca, nggak pernah *menghentikan* apa pun.

### 5. Worker bisa nge-block dirinya sendiri
Worker satu event loop asyncio, heartbeat tiap 10 detik, job dianggap mati bila heartbeat >60 detik — tapi faster-whisper itu CPU/GPU sinkron. Kalau `align` jalan di loop, heartbeat ikut macet dan job sehat bisa dinyatakan `WorkerInterrupted` oleh sistemnya sendiri. Spec nggak pernah mewajibkan align (dan olah gambar Pillow) jalan di executor/process pool. Pola ambil job Postgres-nya juga bukan pola `SKIP LOCKED` yang lazim (CTE) — perlu dibuktikan dengan tes konkuren multi-worker.

### 6. Pabriknya berhenti di ZIP
Nggak ada tahap upload/publish ke YouTube, TikTok, atau Reels di fase mana pun — Fase 7 cuma soal deploy. Kalau tujuannya full automation kayak pertanyaan awal, last mile-nya masih manual tiap video. Kalau itu memang disengaja sebagai human-in-the-loop, tulis eksplisit sebagai non-goal; kalau bukan, ini **Fase 8 yang hilang**.

## Catatan kecil tapi nyata

- Peringatan durasi render di 8.7 masih hardcode 30–40 detik padahal `target_min_s`/`target_max_s` bisa diubah per project.
- Rotasi/hilangnya `APP_SECRET_KEY` nggak dibahas (hilang kunci = semua API key provider nggak bisa didekripsi, dan backup Fase 7 nggak nyebut secret).
- `resource_key` buat image ambigu antara `image:<provider>` di 7.2 dan contoh `image:<ulid>` di 2.3.
- `retry_safe` buat job lokal (align/render/export) nggak terdefinisi padahal pemulihan heartbeat bergantung padanya.
- BGM/SFX unggahan pemilik nggak punya field lisensi/sumber, padahal itu risiko Content ID dan `project.json` nggak mencatatnya.

## Catatan builder — kesiapan environment VM (dicek 2026-10-21 ~12:00 WIB)

- Python 3.12.3 ✓, ffmpeg 8.1.2 ✓, node v24.20.0 + npx ✓ — fondasi runtime siap.
- **Belum ada:** fastapi, uvicorn, sqlalchemy, pydantic, faster-whisper (pip); belum ada scaffold React/Vite.
- Kalau spec di-"gas" jadi build, langkah pertama: `python -m venv` + pip install dependency backend, dan `npx create-vite` untuk SPA. Belum dikerjakan — nunggu keputusan.
