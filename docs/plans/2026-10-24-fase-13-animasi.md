# Fase 13 — Animasi Tier A+B (Keputusan Pemilik)

Status: PLAN — disetujui pemilik 2026-10-24 ~14:33 WIB ("Gas, jadikan standar pabrik").
Tanggal: 2026-10-24. Cabang: `feat/fase-13-animasi` dari `feat/speed-110-default`
(HEAD dd4b490, sudah memuat Fase 12 + speed-110).

## Asal-usul: vonis pemilik + prototipe yang sudah ditonton

Pemilik (2026-10-24 ~14:08 WIB): video sekarang "gambar digabung, rawan
penonton bosan", minta animasi + ide lain. Agen menjawab tiga tier; pemilik
memilih **A+B dulu** (~14:11 WIB), lalu menonton prototipe dan mengesahkan
menjadi standar pabrik (~14:33 WIB).

Prototipe (skrip `prototype-ab/build_prototype.py`, TIDAK di-commit — referensi
di working tree): render ulang materi video BUMN 2026-10-24 (project
`01M5NK24SX1EHJN2JEE3A70VBM`, script aktif `01M5NK80PCJQKKNDJYN0TTY9KX`,
9 scene, suara Aria) dengan graf FFmpeg baru. Hasil terverifikasi frame per
frame: **44,1 detik, 1080×1920, audio AAC**, sama dengan render produksi v5.
Dua bug prototipe ditemukan dan diperbaiki sebelum pengesahan (keduanya
menjadi aturan implementasi di bawah):
1. ASS karaoke tanpa header PlayResX/PlayResY → libass tidak menggambar
   subtitle sama sekali (frame hitam total pada tes isolasi). Header PlayRes
   1080×1920 wajib.
2. Arah karaoke libass terbalik dari dugaan awal: tag `\k` menggambar kata
   yang SUDAH terucap dengan PrimaryColour dan kata yang BELUM terucap
   dengan SecondaryColour (terverifikasi dua frame). Supaya kata menyala
   kuning saat diucapkan: Primary=kuning, Secondary=putih.

## Desain (port prototipe ke pabrik, satu-satu)

### A. Gerakan lebih berani — `app/services/render_plan.py`, `render_ffmpeg.py`
- `SceneInput` + `RenderScene` mendapat field `beat` (diplumb dari
  `Scene.beat`; kolom sudah ada di model).
- `_pick_motion`: beat hook/twist/impact → `punch_in` (aturan closeup →
  punch_in dipertahankan). Selain itu pilihan deterministik lama.
- Zoompan diperkuat: zoom 8% → **22%** (`1+0.22*on/d`), pan sweep 3% → 5%
  pada zoom dasar 1.22, `punch_in` = 1→1.15 dalam 12 frame pertama lalu tahan.

### B. Transisi — `render_ffmpeg.py`
- Setiap batas scene menjadi xfade **0,35 detik** (tpad clone kedua sisi
  0,175 detik, seperti logika lama): `fade` biasa, **`slideleft` masuk
  scene twist**. Ini mempensiunkan concat hard-cut untuk transisi `cut`
  (field `Scene.transition` tetap di model/API, tidak lagi memilih concat
  vs xfade di graf render). Whoosh transisi tetap dipusatkan di batas.
- Alasan: prototipe yang disahkan pemilik memakai fade di semua batas.

### C. Keyword overlay animasi — `app/jobs/render.py`, `render_ffmpeg.py`,
   `app/services/thumbnail_text.py`
- `jobs/render.py` BERHENTI mengomposit keyword ke gambar scene sebelum
  ffmpeg. Sebagai gantinya: `keyword_text` mengalir lewat `SceneInput` →
  `RenderScene.keyword_text`; job render menulis PNG transparan per scene
  (gaya sama: Plus Jakarta Sans ExtraBold, mulai 150px, maks 2 baris,
  lebar maks 940px, putih + stroke hitam, y=90) dari fungsi baru
  `draw_keyword_overlay` (refaktor `_draw_top_text` agar bisa kanvas RGBA).
- `render_ffmpeg.py` menambah input looped per keyword + overlay:
  geser dari +60px ke tengah selama 0,3 detik pertama scene
  (`x='(W-w)/2+60*max(0,1-t/0.3)'`) + fade-in alpha 0,3 detik.
- Gambar scene mentah tetap tanpa teks; tidak ada teks ganda (terverifikasi
  frame prototipe).

### D. Subtitle karaoke — `app/services/subtitles.py`
- `build_ass` menulis tag `\k<durasi_cs>` per kata (durasi dari word
  timings; minimal 1cs), memakai line-wrap yang sama dengan sekarang.
- Header PlayResX 1080 / PlayResY 1920 / WrapStyle 2 dipertahankan (sudah
  ada) — JANGAN dihapus, tanpanya subtitle hilang total (bug prototipe 1).
- Warna karaoke: Primary=kuning (`&H0000FFFF`), Secondary=putih
  (`&H00FFFFFF`) — arah libass per bug prototipe 2.
- TRADEOFF TERCATAT: tag emphasis emas per kata (`\c`) dihapus di mode
  karaoke — highlight kuning per kata yang terucap menggantikan fungsi
  emphasis. Field `emphasis_words` tetap ada untuk validasi.

### E. Goyang kamera di cue SFX — `render_ffmpeg.py`
- Scene yang memuat cue SFX (boom/punch/dll.) mendapat overscan
  `scale=1140:2028` + `crop=1080:1920` dengan offset sinus ±12px pada
  18 Hz selama jendela 0,4 detik sejak kata pemicu
  (`x='30+12*sin(2*PI*18*t)*between(t,c0,c1)'`, y cosinus).
  Waktu lokal cue dipetakan dari `plan.sfx_events` (global) ke scene.
- E2E wajib memverifikasi goyang ini (bukan dari still frame — bandingkan
  dua frame 0,05 detik berselang di jendela goyang, harus ada pergeseran
  piksel; di prototipe goyang hanya diimplementasi, belum diverifikasi
  visual).

### F. Invalisasi cache render lama — `app/jobs/render.py`
- Perubahan di atas adalah level kode, bukan style dict — digest lama yang
  sama akan mengembalikan video lama dari cache. Tambahkan konstanta
  `RENDER_GRAPH_VERSION = "fase-13"` ke `render_hash_parts` sehingga
  semua render lama sekali invalid dan proyek yang di-render ulang
  mendapat graf baru. Tes mengunci versi ini.

## Tugas (TDD, satu commit per tugas)
1. `render_plan`: field beat + motion punch_in per beat + zoom 22%.
2. `render_ffmpeg`: xfade semua batas (fade/slideleft twist) + keyword
   overlay inputs + shake crop.
3. `thumbnail_text`: `draw_keyword_overlay` (kanvas RGBA).
4. `jobs/render`: alur keyword overlay + `RENDER_GRAPH_VERSION` di hash.
5. `subtitles`: karaoke `\k` + warna primer/sekunder karaoke.
6. E2E: `run_render` langsung (tanpa job/DB tulis, tanpa publish) pada
   plan BUMN → verifikasi durasi 44,1 dtk, frame keyword/karaoke/twist,
   dan pergeseran piksel di jendela goyang; bandingkan dengan prototipe.
7. Review diff menyeluruh, commit, push origin, restart API+worker dengan
   kode baru (restart dilakukan siang hari, jauh sebelum slot 18:00).

## Rollout & batasan
- TIDAK ada perubahan teks cron produksi: motion/overlay/karaoke/shake
  otomatis dari beat/keyword_text/sfx_cues yang sudah ditulis agen.
  Produksi harian berikutnya (2026-10-25 06:54) memakai Fase 13 otomatis
  setelah branch ini ter-checkout di working tree.
- Slot karhutla 18:00 HARI INI tidak tersentuh: render v3-nya sudah jadi
  dan disetujui (speed 100); Fase 13 hanya berlaku untuk render BARU
  (hash version bump tidak me-render ulang apa pun dengan sendirinya).
- Kriteria penutup fase = suite hijau + ruff bersih + E2E terverifikasi
  (vonis "tes mata" pemilik atas prototipe sudah didapat 14:33 WIB;
  E2E fase ini membuktikan port pabrik setara prototipe, bukan meminta
  vonis kedua).
