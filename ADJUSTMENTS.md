# Penyesuaian Spec: Muse sebagai Generator (Ide, Script, TTS, Video, Thumbnail)

Tanggal: 2026-10-21. Melengkapi `Spec.md` — bukan menggantikannya.
Flow dari pemilik: Muse cari ide → script narasi + visual prompt + cue SFX →
TTS → video per scene → render gabung 30–40 dtk → 1 gambar thumbnail.

## Fakta kemampuan Muse (terverifikasi di VM ini)

- Video: klip **±10 detik, durasi tidak bisa diminta** (docs media). 4–6 dtk/scene
  dicapai dengan **memotong** klip di render, seperti rencana Fase 6s.
  Maks **6 klip video per giliran/turn** — ini batas paling keras di seluruh flow.
- Ada CLI lokal di VM: `media-generation` (gambar/video, orientasi vertical,
  `--image-file` untuk gambar referensi, resume snapshot) dan `tts`
  (suara, `language`, `speed` 1–200, mp3). Keduanya bisa dipanggil worker
  sebagai subprocess — adapter lokal, bukan HTTP API.
- CLI itu **hanya ada di lingkungan Muse**, tidak ikut ke VPS. Fase 7 (deploy
  VPS) tidak kompatibel dengan provider Muse kecuali VPS memanggil balik
  ke lingkungan ini. Abstraksi ProviderRouter di spec menyelamatkan desain:
  adapter Muse untuk sekarang, adapter relay/OpenAI-compatible untuk VPS nanti.
- TTS Muse **tidak mengembalikan timestamp kata** → alignment Whisper bukan
  fallback, tapi jalur utama (spec 4.7 sudah menampung ini).
- Video hasil generate membawa **audio sintesis bawaan** (bisa musik / suara
  semu) → audio harus dibuang **saat ingest**, bukan menunggu render.
- Generate video/gambar adalah generasi segar, bukan animasi frame-exact dari
  storyboard → konsistensi maskot tidak dijamin; terbantu desain stickman
  sederhana + gambar referensi di setiap panggilan.
- Muse tidak bisa menonton video, tapi **bisa memeriksa frame** hasil ekstrak
  ffmpeg → tahap QC frame itu mungkin.

## Delta terhadap Spec.md

1. **Provider (Bab 5)** — tambah adapter `muse_cli` untuk voice/image/video
   yang memanggil `tts` / `media-generation` lewat subprocess. Tanpa API key,
   tanpa harga per panggilan di `provider_model` (biaya = langganan, catat
   sebagai `unknown`/flat di usage). `retry_safe: false` untuk video
   (retry = generasi baru, hasil visual berbeda). Timeout video naikkan
   300 → 900 dtk seperti relay gambar.
2. **Pacing mode video (3.2, 4.3)** — target 30–40 dtk ÷ 4–6 dtk per scene =
   **6–8 scene**, bukan 8–14. Batas cek khusus mode video: `scene_count` 6–8,
   voiceover ±9–15 kata/scene, total ±70–90 kata. Kalibrasi `wps` harus diukur
   dari TTS Muse (default 2,3 di spec berasal dari provider lain).
   Rekomendasi kunci: 6 scene × ±5,5–6 dtk ≈ 35 dtk (satu batch, di bawah
   batas 6 klip per giliran); 7–8 scene tetap sah tapi berarti 2 batch.
3. **Render video (Bab 8)** — `RenderScene` tambah `video_trim_start_s`:
   potong jendela tengah klip 10 dtk (awal klip rawan morph/settle, ujung rawan
   drift). Aturan gerak 8.3 (zoompan) tidak berlaku untuk scene video; ganti
   scale/crop ke 1080×1920 dengan titik pusat vertikal 40% seperti gambar.
   Verifikasi dimensi aktual klip dengan ffprobe saat ingest.
4. **Tahap QC frame baru (antara video dan render)** — ekstrak 3–4 frame per
   klip, periksa: maskot hadir & konsisten, tidak ada teks sampah, aksi kurang
   lebih sesuai prompt. Gagal → maks 1× regenerate per scene (ingat jatah
   6 klip per giliran: regen berarti batch tambahan).
5. **SFX event (3.2, 8.2)** — timing tetap diikat ke kata narasi (hasil align),
   BUKAN ke momen visual di klip: aksi di klip generate tidak bisa dikontrol
   frame-exact, jadi SFX yang menuntut sinkron visual presisi (ledakan pas
   benda jatuh) akan sering meleset. SFX transisi & event berbasis kata aman.
6. **Thumbnail (4.14)** — teks judul **jangan digambar AI** (ejaan Indonesia
   tidak dijamin, spec sendiri mengakui tanpa OCR). Konsep tetap dari LLM,
   tapi teks di-composite lokal (Pillow/drawtext) di atas gambar/frame hasil
   generate. Ejaan pasti benar, teks bisa diedit tanpa regenerate gambar.
7. **TTS (4.6)** — pertimbangkan 1 panggilan TTS untuk seluruh narasi lalu
   potong per scene dari hasil align: kontinuitas prosodi lebih baik daripada
   14 panggilan per scene tanpa konteks (`supports_context: false` untuk
   adapter ini). Regenerate per scene tetap ada sebagai perbaikan lokal.
8. **Urutan flow** — Gerbang B (persetujuan script + klaim) menjadi makin
   penting: video adalah sumber daya paling langka/lambat, jadi tidak ada
   generate video sebelum script disetujui. Metadata 3 platform tetap
   sesudah render, seperti spec.
9. **Fase 11 — kualitas narasi & suara (2026-10-23, masukan pemilik atas test
   data center)** — (a) subtitle `margin_v` bawaan 580 → 400 (Spec §8.5 sudah
   diperbarui); (b) durasi bukan lagi target: bawaan `target_min_s/target_max_s`
   = 0/45, `duration_range` hanya error bila estimasi > maks, `duration_short`
   warning bila proyek memasang min > 0 (Spec §4.4 sudah diperbarui);
   (c) anti-kaku: aturan kalimat utuh + jangkar bahasa di prompt
   (`spoken_indonesian`, `pacing`), check warning `fragment_style`,
   `validate.script` v4 menilai keluwesan tuturan; (d) QC bahasa per klip
   suara (`app/services/lang_qc.py`): deteksi faster-whisper reuse model
   aligner, lolos = id ≥ 0,60, regenerasi maks 2×, hasil di `asset.data`
   (`lang_qc`) + warning job; aktif hanya bila `WHISPER_MODEL` terpasang.
   Catatan jujur: Whisper sulit membedakan id vs ms — QC menangkap drift
   kasar; penilai akhir tetap telinga pemilik.

## Spike Fase 0 yang harus jalan sebelum angka dikunci

Satu episode stickman ujung-ke-ujung memakai flow ini, mengukur:
durasi & dimensi aktual klip video CLI, wps aktual TTS Muse bahasa Indonesia,
konsistensi maskot antar klip dengan gambar referensi, kualitas QC frame,
dan total waktu produksi per episode.
