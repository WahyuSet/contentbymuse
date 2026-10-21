# Fase 6 — Render: Rencana Implementasi

> **DISETUJUI pemilik 2026-10-21 20:48 WIB ("gas Fase 6")** — draft riset latar 20:05 dijalankan dengan amendemen:
> A1. AppSetting di kode yang ada adalah tabel key/value JSON, jadi `subtitle_style` disimpan sebagai baris kunci — **migrasi 0006 tidak diperlukan**; Task 1 menjadi bundling font + penanam/pengakses `subtitle_style` bawaan saja. Kolom project `voice_volume_db`/`bgm_asset_id` dari draft juga gugur: voice_volume adalah `app_setting` (§8.6) dan BGM di luar lingkup (Keputusan 6).
> A2. Empat file render hidup di bawah satu baris aset `render` (kunci video.mp4) dengan `data.files` memuat keempat kunci + `data.encoder`/`duration_s`/`warnings`; file lain (srt/ass/thumbnail) tidak menjadi baris aset sendiri.
> A3. Direktori ledger: `.superpowers/sdd/fase-6-render/`.
> Untuk agen pelaksana: Wajib memakai sub-skill: gunakan superpowers:subagent-driven-development (disarankan) atau superpowers:executing-plans untuk menjalankan rencana ini per task. Langkah memakai kotak centang (`- [ ]`) untuk pelacakan. Gaya UI mengikuti antislop (identitas Fase 1-5) dan komentar kode mengikuti antislop-code.

**Tujuan:** Dari script yang disetujui + aset suara & gambar terpilih per scene, hasilkan satu MP4 9:16 (1080×1920, 30fps) dengan subtitle bakar sinkron dari word timings + Ken Burns per scene + audio narasi concat yang di-loudnorm, plus file `.srt`/`.ass` dan thumbnail frame — menutup baris "Render" di spec (§4.9/§8). Render 100% lokal via FFmpeg (gratis, tanpa provider berbayar).

**Arsitektur:** `build_render_plan(project, settings) -> RenderPlan` murni (timeline, motion deterministik, cue subtitle global) → `build_ffmpeg_command(plan, paths) -> list[str]` murni (snapshot-tested) → service `ffmpeg_render` menjalankan graph: gambar `scale=2160:3840 → zoompan` per scene, audio `trim → apad=whole_dur`, concat, bakar `ass`, `loudnorm`, encode (NVENC deteksi → fallback libx264). Job `render` per project: cache `input_hash` (id+versi aset suara/gambar, versi subtitle style, settings) → hash sama = pakai ulang file tanpa FFmpeg. `reconcile` mengantrekan render otomatis (gratis); edit scene / pilih ulang aset memanggil `reconcile_render`; tombol manual `POST /projects/{id}/render` (`force`). Gerbang approved WAJIB di handler + endpoint sejak awal (pelajaran review Fase 5).

**Stack teknologi:** yang sudah ada + FFmpeg 8.1.2 sistem (filter `ass`, `zoompan`, `loudnorm` terverifikasi) + fonttools (instantiate font OFL, sudah ada di VM) + Pillow (ukur lebar subtitle 940px).

## Fakta terverifikasi (riset 2026-10-21, smoke test langsung di aset asli)

Smoke test `/tmp/render-smoke.py` memakai **aset nyata** project cicak Fase 5 (2 scene: PNG 1080×1920 + mp3 suara + word_timings proporsional dari `backend/storage/app.db`):

- Rantai penuh jalan: `scale=2160:3840,zoompan=z='1+0.08*on/97':d=97:fps=30:s=1080x1920` → concat → bakar `ass` → `loudnorm=I=-14:TP=-1.5:LRA=11` → `libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30` + `aac -b:a 192k -ar 48000 -movflags +faststart`.
- Output 6,62 dtk vs rencana 6,56 dtk (toleransi < 0,5 dtk); `ffprobe`: `h264,1080,1920` + `aac` — lolos.
- **Subtitle benar-benar terbakar**: frame t=1,0 dtk dengan vs tanpa filter `ass` → 39.801 piksel berubah. Tag emphasis `{\c&H4DD8FF&\fscx110\fscy110}` (kuning `#FFD84D` + 110%) di-parse libass tanpa error.
- **Ken Burns benar-benar bergerak**: frame pertama vs terakhir scene 0 → 107.098 piksel berubah (zoom 1,00→1,08 halus, tanpa getar).
- Timeline §8.2 terverifikasi: scene 0: audio 3,17 dtk → segmen 3,25 dtk (+0,08); scene terakhir 2,83 → 3,31 (+0,08+0,4). Pembulatan bingkai `int(t*30+0,5)` tidak menumpuk.
- Thumbnail: frame t=0,5 dtk scene 1 → JPEG 1080×1920 (kualitas `-q:v 2` ≈ q90).
- **NVENC ada di daftar encoder tapi GAGAL** di VM ini (tanpa GPU) — persis alasan spec §8.7 mewajibkan deteksi via encode satu bingkai uji + fallback `libx264`. Logika deteksi+fallback wajib diimplementasi, encoder tercatat di manifest.
- **Font Plus Jakarta Sans TIDAK ada** di sistem maupun repo. Jalur bundling terverifikasi: unduh OFL variable font (https://github.com/google/fonts/raw/main/ofl/plusjakartasans/PlusJakartaSans%5Bwght%5D.ttf, 176 KB, 200 OK) → `fonttools.varLib.instancer` wght=800 → `PlusJakartaSans-ExtraBold.ttf` statis (`usWeightClass` 800) → libass me-render-nya (42.017 piksel berubah). Draft menetapkan font di-bundle di `app/assets/fonts/` + `fontsdir` eksplisit di filter `ass`.
- Estimasi durasi penuh: 10 scene × ~3 dtk + jeda ≈ 32–35 dtk → masuk jendela 30–40 dtk spec §8.7 (peringatan, bukan gagal).

## Konteks dari Spec (mengikat)

- §8.1 `RenderPlan`/`RenderScene`: `build_render_plan` dan `build_ffmpeg_command` fungsi murni, dites snapshot. `RenderScene`: position, image_path, audio_path, audio_trim, duration_s, motion, transition_in, words (sudah waktu global).
- §8.2: durasi scene = clip setelah trim + 0,08 dtk; scene terakhir +0,4 dtk; batas scene dari kumulatif dibulatkan ke bingkai; kata digeser ke waktu global (offset kumulatif − trim.start).
- §8.3: gambar diskalakan ke lebar 2160 sebelum zoompan; zoom_in/out 1,00↔1,08; pan 6% lebar; punch_in 1,00→1,06 dalam 0,2 dtk lalu diam; static. Pemilihan: `diagram` → static/zoom 1,00→1,03; `closeup` → punch_in; lainnya dari `hash(scene.id)` ≠ scene sebelumnya (deterministik).
- §8.4: `cut` default; `crossfade` = `xfade=fade` 8 bingkai, dipusatkan di batas; jadi `cut` bila scene pertama / scene < 0,5 dtk.
- §8.5: cue 2–4 kata, potong awal di `. , ! ? ;`, maks 28 karakter/baris, 940 px (ukur dengan font bundel), maks 2 baris; teks dari `subtitle_override` bila ada (waktu proporsional) else voiceover; gaya default di `app_setting.subtitle_style`: Plus Jakarta Sans ExtraBold 78 px, putih outline hitam 6 px, tanpa kotak, rata tengah, baseline y=1340; emphasis `#FFD84D` + 110% via `\c` `\fscx` `\fscy`; bakar via `ass`, ekspor `.srt` juga.
- §8.6: clip dipotong trim + `apad=whole_dur` → concat; BGM opsional (ulang sepanjang video, −22 dB, ducking `sidechaincompress`, fade-out 1 dtk); `loudnorm=I=-14:TP=-1.5:LRA=11` di master; `voice_volume_db` (0 = graph/hash tak berubah).
- §8.7: `h264_nvenc -preset p5 -cq 21` (deteksi 1 bingkai, cache per path FFmpeg) → fallback `libx264 -preset medium -crf 20`; `yuv420p -r 30`, AAC 192k 48k, `+faststart`; thumbnail frame 0,5 dtk scene 1 JPEG q90; verifikasi durasi via ffprobe; hasil kosong / < rencana−0,5 dtk ditolak; di luar 30–40 dtk = peringatan.
- §8 akhir: render memakai `-progress pipe:1` (`out_time_ms ÷ total`).
- §9: `POST /projects/{id}/render` manual (`force`); 409 `ScriptNotApproved`, `RenderNotReady`, `RenderUpToDate`; job aktif → `created=false`.
- Baris 575: render gratis → `reconcile` membuatnya sendiri; `enqueue` biasa (bukan once) agar hash yang kembali ke nilai lama dapat job baru yang memakai cache; setujui script baru membatalkan job render; `reconcile_render` hanya mengurus render (tak pernah memicu suara/gambar/metadata).
- §4.11 Export: butuh render terpilih + keempat filenya (video.mp4, subtitles.srt, subtitles.ass, thumbnail.jpg) — fase ini menyiapkan keempatnya; ZIP-nya fase berikutnya.
- ADJUSTMENTS.md: event SFX mengikuti kata narasi (bukan momen visual) — tetapi **tak ada satu pun kode SFX di backend** (library SFX = sub-fase 6c/6f spec), jadi di luar lingkup fase ini.

## Keputusan lingkup fase ini

1. **Fase 6 = render inti saja.** Sub-fase spec 6c/6f (pustaka SFX), 6g (watermark `@SiKlepon-id`), 6b/4.14 (thumbnail konsep AI + composite teks lokal), 6i (ending loop/cta), 6m (metadata), 4.11 (export ZIP) = fase berikutnya. Alasan: tak ada kode SFX/watermark/thumbnail-AI di backend; render inti sudah memberi video tonton + 4 file untuk ekspor.
2. **Font di-bundle, bukan dari sistem.** `app/assets/fonts/PlusJakartaSans-ExtraBold.ttf` (OFL) dihasilkan sekali via fonttools instancer wght=800 dari URL terverifikasi di atas; filter `ass` selalu memakai `fontsdir` absolut ke folder itu. Tanpa font → render gagal dengan pesan jelas (bukan fallback diam-diam).
3. **Encoder: deteksi NVENC → fallback libx264.** Encode 1 bingkai uji saat startup/worker-init, cache per path FFmpeg; gagal → `libx264 -preset medium -crf 20`. Encoder + `render_seconds` + `duration_s` tercatat di manifest/log job.
4. **Motion deterministik penuh** per §8.3 (hash scene.id, anti-ulang tetangga); `transition_in` default `cut` untuk semua (crossfade = opsi manual per scene di UI bila sempat, else fase berikut — graph sudah mendukung `xfade`).
5. **Subtitle: bakar + ekspor.** `ass` dibakar ke video; file `.srt` + `.ass` disimpan sebagai aset render untuk ekspor ZIP. `subtitle_override` didukung (waktu proporsional); `emphasis_words` dari scene bila ada.
6. **Audio: suara saja + loudnorm.** BGM: settings ada, default `None` (tanpa track bawaan — unggah menyusul); `voice_volume_db` default 0. Tanpa SFX (keputusan 1).
7. **Pemicu: reconcile otomatis + tombol manual.** `reconcile` mengantrekan render bila script approved dan semua scene punya voice+image terpilih; `reconcile_render` dipanggil saat edit scene / pilih ulang aset; `POST /render` manual + `force`. **Gerbang approved di handler DAN endpoint sejak task pertama** (pelajaran Fase 5).
8. **Cache render by hash.** `input_hash` = hash(id+versi aset voice & image terpilih, versi subtitle style, settings render). Hash sama → pakai ulang file (`cached`, tanpa FFmpeg). Durasi di luar 30–40 dtk → peringatan di hasil job, bukan gagal.

## Konvensi global

- Warisan Fase 1-5: ULID, UTC, `/api`, error standar, pesan Indonesia, TDD, commit per task, ruff bersih, komentar seperlunya (antislop-code).
- Branch `feat/fase-6-render` dari ujung `feat/fase-5-gambar`. `HANDLERS` bertambah `render`.
- Penyimpanan file hanya lewat `LocalStorage`; kunci aset: `assets/{project_id}/render-v{version}/video.mp4` (+ `subtitles.srt`, `subtitles.ass`, `thumbnail.jpg`).
- `build_ffmpeg_command` TIDAK mengeksekusi apa pun — murni list argv (mudah snapshot-test); eksekusi + `-progress` di service terpisah.

---

### Task 1: Settings render (app_setting) + bundling font

**File:**
- Buat: `backend/app/assets/fonts/PlusJakartaSans-ExtraBold.ttf` (dibangkitkan via skrip `backend/scripts/bundle_font.py`: unduh variable OFL → instancer wght=800; URL + SHA tercatat di skrip)
- Buat: `backend/app/services/render_settings.py` (`get_subtitle_style(session)` membaca baris AppSetting `subtitle_style`, menanam bawaan bila belum ada)
- Buat: `backend/tests/test_render_seed.py`

**Antarmuka:**
- `subtitle_style` default: `{font: "PlusJakartaSans-ExtraBold", size: 78, outline: 6, margin_v: 580, max_width_px: 940, max_chars: 28, emphasis_color: "#FFD84D"}`.
- Skrip bundling idempoten: lewati bila TTF sudah ada dan valid (`usWeightClass==800`).

- [ ] **Langkah 1: Tes** — get_subtitle_style menanam + mengembalikan bawaan yang valid dan idempoten; skrip bundling menghasilkan TTF 800 dari fixture variable font lokal (tanpa network di tes).
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-6): settings render + bundling font`

### Task 2: build_render_plan + build_ffmpeg_command (murni, snapshot)

**File:**
- Buat: `backend/app/services/render_plan.py` (`RenderScene`, `RenderPlan`, `SubtitleStyle`, `build_render_plan`)
- Buat: `backend/app/services/render_ffmpeg.py` (`build_ffmpeg_command(plan, paths) -> list[str]`)
- Buat: `backend/tests/test_render_plan.py` (+ snapshot `tests/snapshots/render_cmd_*.txt`)

**Antarmuka:**
- `build_render_plan(project, scenes, assets, settings)`: durasi = trim audio + 0,08 (+0,4 terakhir); batas dibulatkan ke bingkai 30fps; kata → waktu global; motion per §8.3 (hash stabil, anti-ulang); cue subtitle 2–4 kata + potong di tanda baca.
- `build_ffmpeg_command`: argv lengkap per rencana smoke test (scale 2160 → zoompan, apad, concat, ass+fontsdir, loudnorm, encoder by detection, faststart); escaping koma filtergraph benar.

- [ ] **Langkah 1: Tes** — 3 scene sintetis: durasi/batas/motion/cue sesuai §8.2–8.5; snapshot argv stabil; `diagram`→static, `closeup`→punch_in.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-6): render plan murni + snapshot`

### Task 3: Builder subtitle (ASS + SRT)

**File:**
- Buat: `backend/app/services/subtitles.py` (`build_ass(cues, style, font_path) -> str`, `build_srt(cues) -> str`, `chunk_cues(words) -> cues`)
- Buat: `backend/tests/test_subtitles.py`

**Antarmuka:**
- `chunk_cues`: 2–4 kata, potong awal di `. , ! ? ;`, ≤28 karakter/baris, ≤940 px (ukur via Pillow + font bundel), maks 2 baris; `subtitle_override` → bagi proporsional; `emphasis_words` → tag `\c` + `\fscx110\fscy110`.
- ASS: `PlayResX 1080 / PlayResY 1920`, `MarginV 580` (= baseline y 1340), outline 6, tanpa kotak.

- [ ] **Langkah 1: Tes** — golden ASS untuk kata contoh (c Indonesia + tanda baca + emphasis); SRT valid; baris >940px terpecah.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-6): builder subtitle ASS/SRT`

### Task 4: Service FFmpeg render (eksekusi + deteksi encoder)

**File:**
- Buat: `backend/app/services/ffmpeg_render.py` (`detect_encoder()`, `run_render(plan, paths, workdir, progress_cb) -> RenderResult`)
- Buat: `backend/tests/test_ffmpeg_render.py`

**Antarmuka:**
- `detect_encoder()`: encode 1 bingkai uji `h264_nvenc`; cache per path FFmpeg; gagal → `libx264`. Hasil: `{encoder: "h264_nvenc"|"libx264", args: [...]}`.
- `run_render`: tulis ASS ke workdir; jalankan argv dari Task 2 dengan `-progress pipe:1` → `progress_cb(out_time_ms/total)`; tolak hasil kosong / durasi < rencana−0,5 dtk; verifikasi ffprobe; ekstrak thumbnail (0,5 dtk scene 1, JPEG q90); kembalikan `RenderResult(video_path, ass_path, srt_path, thumbnail_path, duration_s, encoder, render_seconds)`.
- Error FFmpeg → `ServerError` pesan Indonesia menyebut tahapnya (bukan retry otomatis: render deterministik, ulang manual via force).

- [ ] **Langkah 1: Tes** — deteksi dengan ffmpeg fake (nvenc gagal → libx264); run_render dengan 2 scene sintetis (gambar Pillow + nada `aevalsrc`) → mp4 valid 1080×1920; progress callback dipanggil; durasi salah → ditolak.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-6): service ffmpeg render`

### Task 5: Job render + reconcile + cache + gerbang approved

**File:**
- Ubah: `backend/app/jobs/render.py` (baru; `run_render_job`), `backend/app/services/reconcile.py` (`reconcile_render`)
- Buat: `backend/tests/test_render_job.py`

**Antarmuka:**
- Handler menolak script `!= approved` (`ScriptInputError`, pelajaran Fase 5 — sejak awal).
- `input_hash` = hash(id+versi aset voice/image terpilih per scene, versi subtitle style, settings); hash sama → tandai `cached`, tanpa FFmpeg.
- `reconcile`: script approved + semua scene punya voice & image terpilih → `enqueue` render (biasa, bukan once). `reconcile_render`: dipanggil edit scene / pilih ulang aset / ubah subtitle style.

- [ ] **Langkah 1: Tes** — script non-approved → ditolak; hash sama → cached tanpa panggil FFmpeg; pilih ulang image → hash beda → job baru; scene tanpa voice → tidak antre.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-6): job render + reconcile`

### Task 6: API render

**File:**
- Ubah: `backend/app/api/projects.py` (`POST /projects/{id}/render`, `GET /projects/{id}/render`)
- Buat: `backend/tests/test_render_api.py`

**Antarmuka:**
- `POST /render` `{force?}` → 409 `ScriptNotApproved` (tanpa approved), `RenderNotReady` (alasan: scene mana kurang aset), `RenderUpToDate` (kecuali force); job aktif → `created=false`.
- `GET /render` → render terpilih: versi, durasi, encoder, peringatan, URL keempat file via `/api/files`.
- Empat file (video.mp4, subtitles.srt, subtitles.ass, thumbnail.jpg) disajikan sebagai aset render.

- [ ] **Langkah 1: Tes API** — skenario 409 satu per satu; force membuat versi baru; file tersaji dengan MIME benar.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-6): API render`

### Task 7: UI render

**File:**
- Ubah: `frontend/src/...` (panel "Render" di detail project: tombol Render, progress bar, pemutar mp4 9:16, unduh 4 file, daftar versi + peringatan; badge `cached`)

**Antarmuka:** mengikuti pola panel Gambar/Suara Fase 4-5; busy state per job render.

- [ ] **Langkah 1: Implementasi** (vitest bila ada logika).
- [ ] **Langkah 2: Hijau** — vitest + build.
- [ ] **Langkah 3: Commit** — `feat(fase-6): UI render`

### Task 8: E2E hidup + review

- [ ] **Langkah 1: E2E hidup** — server + worker; project cicak (10 scene, aset asli Fase 4–5) → `POST /render` → MP4 1080×1920 30fps jadi; subtitle terbakar sinkron (cek 2 cue via ekstrak frame); durasi 30–40 dtk (atau peringatan tercatat); 4 file tersaji; `force` → versi 2; hash sama → `cached` tanpa FFmpeg. Catat `render_seconds` + encoder di ledger.
- [ ] **Langkah 2: Suite segar penuh** — backend pytest + ruff; frontend vitest + build.
- [ ] **Langkah 3: Commit** — `feat(fase-6): e2e render`.
- [ ] **Langkah 4: Review** — paket diff dari ujung Fase 5 → reviewer subagent fresh; fokus: kebenaran timeline vs §8.2, escaping filtergraph, gerbang approved, keamanan path (traversal), cache hash; perbaiki Critical/Important satu pass TDD; Minor ke ledger `.superpowers/sdd/fase-6-render/progress.md`. Perbarui `~/MEMORY.md`.

## Kriteria review akhir

- 0 Critical; Important diperbaiki TDD dalam pass yang sama; suite hijau penuh.
- Video E2E: 1080×1920, 30fps, `yuv420p`, `+faststart`, subtitle terbakar sinkron kata, durasi ≈ jumlah scene, thumbnail valid.
- Pelajaran Fase 5 (gerbang approved) terpenuhi sejak Task 5 — reviewer memverifikasi eksplisit.
