# Fase 12 (mini) — Disiplin Visual Maskot: Kunci Identitas Tikus Berdasi

Status: PLAN — menunggu persetujuan pemilik untuk dibangun.
Tanggal: 2026-10-23. Cabang usulan: `feat/fase-12-visual-maskot` dari ujung `feat/fase-11-kualitas`.

## Asal-usul: penilaian jujur maskot (perintah pemilik)

Pemilik meminta penilaian jujur: maskot kita bagaimana, perlu rebranding? Vonis agen (berdasarkan gambar referensi + frame sheet produksi): **konsep TIDAK perlu rebranding** — "Tikus Berdasi" adalah simbol satir yang sudah hidup di budaya politik Indonesia (ekuitas nama/handle/sudah-terbit jangan dibuang). Yang lemah adalah **disiplin eksekusi karakter**, terdiagnosis dari bukti frame:

1. **Proporsi melayang** antar-scene (±70% konsisten): gendut/kurus, kepala besar/kecil, ketebalan garis berubah — frame "SEWA TOKO" tampak digambar tangan lain.
2. **Ekspresi satu nada**: hampir semua frame memakai muka yang sama (seringai licik mata setengah tertutup), termasuk di beat yang butuh reaksi berbeda.
3. **Peran kabur**: maskot adalah simbol oknum (penjahat yang diekspos narasi), tetapi di banyak frame ia berperan presenter yang menunjuk-nunjuk ke penonton.
4. **Sering kecil/absen**: beberapa scene maskot mungil atau tidak ada sama sekali.

Akar masalah terverifikasi di pabrik: gaya "Tikus Klasik" hanya punya `mascot_anchor` SATU kalimat berbahasa Inggris yang (a) justru mengunci satu ekspresi itu sebagai definisi karakter, (b) tidak menyebut proporsi/bobot garis sama sekali, dan (c) hanya ditopang SATU gambar referensi satu pose (`storage/assets/global/reference/tikus-berdasi.jpg`). Lapisan prompt ikut menyumbang: blok `mascot.md` mengizinkan 2–3 scene tanpa maskot dan tidak mengatur peran/ekspresi/skala. Pembagian beban: ±70% lapisan style, ±30% lapisan prompt. Tuning dikerjakan style dulu, prompt sesudahnya. **Rasa gambar TIDAK diubah**: doodle datar garis tipis, kertas krem hangat, warna muted, dasi merah sebagai satu-satunya warna pop — itu identitas visual channel.

Semua teks yang menghadap mesin gambar (jangkar, style, prompt scene) tetap **bahasa Inggris** sesuai arsitektur pabrik (model gambar jauh lebih patuh pada prompt Inggris); yang berbahasa Indonesia hanya sisi penonton (VO, subtitle, judul, thumbnail).

## Desain

### 1. Aset referensi baru: character sheet (satu gambar)

Pabrik hanya mendukung SATU `reference_asset_id` per gaya — jadi referensinya diganti satu gambar **character sheet** yang digenerate via CLI media-generation (VM ini), berisi dalam satu kanvas:
- pose badan penuh netral (acuan proporsi + kostum + koper uang),
- pose khas (tertawa sambil menghitung uang dari koper),
- deretan kepala dengan 5 ekspresi baku (lihat §2).

Syarat gambar mengikuti aturan pemilik: **tanpa teks apa pun** di gambar (tanpa label ekspresi tertulis), gaya doodle yang sama, latar kertas krem polos. Sheet disimpan di `storage/assets/global/reference/tikus-berdasi-sheet.jpg`.

**Gerbang pemilik:** sheet ditunjukkan ke pemilik dan hanya dipasang sebagai referensi setelah ia menyetujuinya ("tes mata" tahap 1). Bila ditolak, regenerasi sheet (maks 3 kandidat) — bukan tuning buta.

### 2. Jangkar maskot ditulis ulang (kunci proporsi + set ekspresi)

`mascot_anchor` baru (bahasa Inggris, diakhiri tepat satu titik sesuai normalisasi pabrik) — draf final:

"Tikus Berdasi, a cartoon grey rat with FIXED consistent proportions in every scene: a large head about half of his total height, a long pointed snout, big round ears, a round belly, short limbs and a long segmented tail, drawn with thin even black lineart. He always wears a black suit jacket, a white shirt and a bright red necktie, and usually carries a briefcase full of cash. His face uses one of five fixed expressions: a smug sly grin with half-closed eyes (default), a gleeful laugh while counting money, shocked wide-eyed panic when caught, a fake innocent wide smile with both paws raised, or an angry defensive scowl."

- `style_text`: ditambah penegasan bobot garis konsisten ("the same thin, even line weight in every scene") tanpa mengubah rasa doodle/kertas/warna yang ada.
- `negative_text`: ditambah "inconsistent character proportions, chibi proportions, thick bold outlines, different character design, changing face".
- Diterapkan di DUA tempat agar tidak hilang saat DB dibangun ulang: (a) `app/services/styles_seed.py` (seed "Tikus Klasik"), (b) baris live di DB lewat `PATCH /api/visual-styles/{id}` (menaikkan version; nilai lama dicatat di ledger sebelum diubah = jalur rollback).

### 3. Blok prompt: peran, panggilan ekspresi, skala

`app/prompts/blocks/mascot.md` ditulis ulang (bahasa Inggris, mengikuti pola blok lain):
- **Peran pelaku, bukan presenter:** maskot MELAKUKAN perbuatan yang dikritik naskah (menghitung uang, menyelinap, pose pencitraan, bersembunyi di balik berkas, ketahuan) — tidak pernah berdiri menjelaskan/menunjuk ke arah penonton seperti presenter.
- **Panggilan ekspresi wajib:** setiap scene bermaskot memilih SATU ekspresi dari set §2 sesuai beat — panduan bawaan: hook = smug, twist = shocked panic, impact = gleeful/smug, cta = fake innocent; penulis scene menuliskan nama ekspresinya di `visual_prompt`.
- **Skala:** scene bermaskot menjadikan tikus subjek terbesar di frame (±40% tinggi frame, tengah-atas per aturan safe-zone yang ada).
- **Kehadiran:** wajib di scene 1; scene tanpa maskot maksimal 2 per video dan tidak boleh di scene penutup (memperketat izin lama 2–3 scene).
`app/prompts/blocks/visual_rules.md`: tambah satu baris komposisi — bila maskot hadir, ia figur terbesar di frame.

### 4. Teks cron produksi (disiapkan, agen induk yang menerapkan)

Butir tambahan Langkah 4 `tikus-daily-production` sejajar butir Fase 11: penulis scene wajib (a) memilih ekspresi per beat dari set baku dan menuliskannya di visual_prompt, (b) memerankan maskot sebagai pelaku perbuatan yang dikritik, bukan presenter, (c) maskot besar sebagai subjek utama frame, hadir di scene 1, absen maksimal 2 scene dan tidak di penutup.

### 5. Uji A/B — "tes mata"

Project uji TANPA publish memakai ulang 10 scene video data center (project 01M5MFRM9NXPSY9A0E713NAZ9Z): prompt visual sama, ditambah panggilan ekspresi per beat; gambar digenerate dengan gaya baru; frame sheet BARU disusun berdampingan dengan sheet LAMA (`.superpowers/sdd/fase-11-kualitas/e2e-frames/contact_sheet.jpg`). Kriteria lulus (penilaian visual agen + verdict pemilik):
- Proporsi & bobot garis tampak sama di 10/10 frame baru (tidak ada frame "digambar tangan lain").
- ≥4 ekspresi berbeda terpakai sesuai beat.
- Maskot subjek dominan di semua scene bermaskot; tidak ada scene bermaskot yang mungil/absen.
Record publish project uji dinetralkan seperti biasa; 0 awaiting di akhir.

## Tugas

1. Generate character sheet (maks 3 kandidat) → gerbang persetujuan pemilik → pasang sebagai aset referensi gaya (file + `reference_asset_id`).
2. Tulis ulang `mascot_anchor` + tambahan `style_text`/`negative_text` di styles_seed + PATCH live + tes seed/API terkait.
3. Tulis ulang blok `mascot.md` + satu baris `visual_rules.md` + tes konten prompt.
4. Siapkan teks cron (file) untuk agen induk.
5. Uji A/B: project uji 10 scene, generate gambar gaya baru, sheet berdampingan lama/baru, laporan penilaian kriteria.
6. Sinkron dokumen: catat perubahan gaya di ADJUSTMENTS.md (nilai jangkar lama tersimpan di ledger untuk rollback).

## Kriteria sukses

- Suite tidak regresi (baseline 326 passed), ruff bersih.
- Character sheet disetujui pemilik dan terpasang sebagai referensi live (terverifikasi dari DB).
- Uji A/B memenuhi 3 kriteria visual di atas dan **"tes mata" pemilik menyatakan LULUS** — verdict pemilik menutup fase, pola tes mute/baca/dengar.

## Di luar cakupan

- Mengganti teknik gambar (tetap doodle kertas) atau mengganti maskot/konsep (tidak ada rebranding).
- Dukungan multi-referensi per gaya (pabrik satu referensi; sheet adalah jalan keluarnya).
- Animasi/gerak karakter; perubahan thumbnail atau UI.
