# Fase 11 — Kualitas Narasi & Suara (Concern Pemilik)

Status: PLAN — menunggu persetujuan pemilik untuk dibangun.
Tanggal: 2026-10-23. Cabang usulan: `feat/fase-11-kualitas` dari ujung `feat/fase-10-twist-cta`.

## Asal-usul: tiga temuan pemilik + satu aturan baru

Pemilik menonton video test data center (project 01M5MCB5TPTRZ88FDNJXY3AZAS, render 38,6 dtk) dan memberi tiga vonis, semuanya terverifikasi agen ke data pabrik:

1. **Subtitle terlalu tinggi.** Setting `subtitle_style.margin_v = 580` → garis dasar teks di y=1340 dari 1920 (30% dari bawah). Bawaan Spec §8.5 di `app/services/render_settings.py` (`DEFAULT_SUBTITLE_STYLE`).
2. **TTS tidak konsisten — logat berubah antar-scene (Indonesia–Inggris–Malaysia).** Terverifikasi BUKAN tertukar suara: 10/10 klip voice dari provider + suara Aria yang sama. Akar masalah: TTS generatif multibahasa disintesis per-scene dari nol (tanpa ingatan antar-klip); parameter bahasa hanya petunjuk; teks pendek yang dibuka kata Inggris ("Data center…", "Investor asing…") memancing tebakan bahasa model berubah tiap klip. Indonesia–Melayu nyaris identik bagi model, jadi drift-nya acak tiga arah.
3. **Narasi kaku.** Efek pemadatan 115→83 kata demi range 30–40 dtk: kata penghubung hilang, sisa fragmen gaya judul berita ("PLN pelanggan raksasa, pajak masuk, data pulang kampung"). Blok `spoken_indonesian.md` saat ini terlalu tipis untuk mencegah gaya fragmen.
4. **Aturan durasi BARU dari pemilik (menggantikan target 30–40 dtk):** video Short cukup **di bawah 45 detik** — 20/25/30 detik boleh, tidak ada lantai wajib. Target durasi kini per-project (`Project.target_min_s/target_max_s`, bawaan model 30/40 di `app/db/models.py`), dipakai check `duration_range` (error dua arah) dan template `blocks/pacing.md` ("70 to 90 spoken words", 2,3 kata/detik).

## Desain per concern

### A. Subtitle turun (margin_v 580 → 400)

- `DEFAULT_SUBTITLE_STYLE.margin_v`: 580 → **400** (garis dasar y=1520/1920 ≈ 21% dari bawah — di atas zona UI Shorts/FB yang menutupi ±15% terbawah untuk teks rata tengah; tombol kanan tetap tidak tertutup karena teks di tengah dengan max_width 940px).
- Baris `app_setting` subtitle_style di DB live diperbarui mengikuti bawaan baru (script operator sekali jalan, tercatat di ledger; get_subtitle_style meng-merge bawaan di atas baris lama, jadi ubah nilai tersimpan secara eksplisit).
- Tes: bawaan baru ter-assert; render plan memakai margin 400; tidak ada tes lain yang mematok 580 (grep dulu).

### B. Durasi: satu-satunya pagar adalah < 45 detik

- Bawaan model: `target_min_s` 30 → **0**, `target_max_s` 40 → **45** (default Python-side; tanpa migrasi — project baru mewarisi, project lama tidak berubah perilakunya kecuali dibuat ulang).
- Check `duration_range` berubah semantik: **error hanya bila estimasi > target_max_s**; di bawah target_min tidak lagi error (bila suatu project masih memasang min > 0, kekurangan durasi menjadi **warning** `duration_short`). Pesan error menyebut batas 45 detik + saran pangkas kata seperti sekarang.
- `blocks/pacing.md` ditulis ulang: target = total estimasi di bawah {{ target_max_s }} detik, kira-kira **maksimal ±100 kata** di 2,3 kata/detik; tidak ada lantai kata; scene tetap 8–14; hook tetap ≤3,5 detik (±7 kata); kalimat scene dianjurkan 8–14 kata utuh (lihat C).
- Cron `tikus-daily-production`: kalimat target durasi di Langkah 4 disesuaikan ("di bawah 45 detik; 20–44 detik semua sah; jangan memangkas naskah sampai kaku demi mengejar 40 detik") — teks disiapkan sebagai file, agen induk yang menerapkan (pola Fase 9/10).

### C. Anti-kaku: aturan kalimat utuh (prompt + check ringan + kriteria validator)

- `blocks/spoken_indonesian.md` diperluas (blok bersama, edit di tempat):
  - **Kalimat utuh wajib:** tiap voiceover adalah kalimat lisan lengkap (subjek + kata kerja), bukan fragmen judul berita; dilarang membuang kata penghubung demi menghemat kata — hemat dari memotong gagasan, bukan dari memotong tata bahasa.
  - Kata penghubung & partikel lisan dianjurkan secukupnya: jadi, nah, tapi, sih, lho, kok, tuh, akhirnya, sementara itu.
  - Tes baca-keras mental: bila kalimat terdengar seperti headline koran, tulis ulang sebagai kalimat orang bercerita.
- Check baru `fragment_style` — **warning** di `run_checks`: scene ditandai bila (a) ≤6 kata DAN tidak memuat kata kerja umum dari daftar kurasi (adalah dikecualikan; daftar: kata kerja berawalan me-/di-/ber- terdeteksi via pola sederhana + daftar kata kerja tak berimbuhan umum: dapat, masuk, naik, turun, jadi, bikin, pakai, dsb. — implementor menyusun daftar dari korpus naskah kita), atau (b) ≥3 koma tanpa kata penghubung. Warning saja: gaya dinilai validator LLM; check ini hanya pengingat mekanis.
- `validate.script` naik **v4**: kriteria baru "keluwesan tuturan" — kalimat utuh seperti orang bercerita; fragmen telegrafis menurunkan skor; contoh buruk dikutip dari video test data center.
- FakeLLM: fixture politik disesuaikan jadi kalimat utuh bergaya lisan (tetap lolos semua check Fase 9/10 + fragment_style tanpa warning).

### D. Anti-drift logat TTS: jangkar bahasa + QC deteksi bahasa

Dua lapis — pencegahan dari teks, dan penangkapan dari audio:

1. **Jangkar bahasa (prompt, masuk `spoken_indonesian.md`):**
   - Jangan membuka kalimat voiceover dengan kata Inggris / nama asing bila ada susunan Indonesia yang wajar; kata Inggris ditaruh di tengah kalimat sesudah konteks Indonesia terbentuk. Di voiceover pakai padanan Indonesia yang hidup ("pusat data") — istilah Inggris tetap dipakai di judul, keyword visual, dan thumbnail untuk pencarian.
   - Hindari singkatan kapital berturut-turut di awal kalimat; eja sebutan lembaga secara wajar.
   - Berlaku juga sebagai instruksi agen penimpa scene di cron (teks file terpisah, agen induk menerapkan).
2. **QC deteksi bahasa per klip (kode):** sesudah job voice menghasilkan klip terpilih per scene, jalankan deteksi bahasa faster-whisper (model align yang sama; panggil `transcribe` tanpa memaksa language pada potongan klip, ambil `info.language` + `info.language_probability`):
   - Klip lolos bila language == "id" dengan probabilitas ≥ 0,60.
   - Klip gagal → **regenerasi otomatis maks 2 kali** (panggilan TTS baru = undian logat baru), simpan hasil terbaik (probabilitas id tertinggi); QC dicatat di `asset.data` (bahasa terdeteksi + probabilitas + jumlah percobaan).
   - Masih gagal sesudah 2 kali → klip terbaik tetap dipakai, job selesai dengan **warning QC** yang terlihat di UI/laporan rantai (tidak memblokir render).
   - Kejujuran teknis yang wajib tertulis di laporan fase: Whisper sulit membedakan id vs ms secara andal — QC ini menangkap drift kasar (Inggris) dan mengundi ulang sisanya; penilai akhir tetap telinga pemilik ("tes dengar").
   - Tes: unit dengan fake aligner/whisper (klip "en" → regenerasi dipanggil; klip "id" → tidak), integrasi job voice dengan QC aktif, batas percobaan dihormati.

### E. Reproduksi bukti (E2E)

Video data center diproduksi ulang sebagai bukti (project baru, TANPA publish): naskah ditulis ulang luwes ±90–100 kata mengikuti aturan C+D (struktur Fase 9/10 utuh: hook klaim, twist berpenanda, kalimat adil, 2 impact, CTA biner, angka hanya 8%), subtitle margin 400, QC bahasa aktif. Deliverable: MP4 + frame sheet + laporan QC per klip (bahasa terdeteksi + probabilitas). Kriteria penutup fase = **"tes dengar" pemilik**: posisi subtitle pas, logat konsisten cukup, narasi mengalir. Keputusan publish video reproduksi = perintah terpisah pemilik.

## Tugas (TDD, satu commit per tugas)

1. Subtitle: bawaan margin_v 400 + update baris app_setting live + tes.
2. Durasi: bawaan target 0/45 + semantik `duration_range` baru (+ warning `duration_short`) + tes (estimasi 44 lolos, 46 error, 20 lolos tanpa error).
3. `pacing.md` + `spoken_indonesian.md` ditulis ulang (aturan B + C + D1) + tes konten prompt.
4. Check `fragment_style` (warning) + tes positif/negatif.
5. `validate.script` v4 (kriteria keluwesan) + FakeLLM kalimat utuh + tes rantai kering.
6. QC deteksi bahasa di job voice: deteksi → regenerasi maks 2 → catat QC + warning job + tes (fake whisper).
7. Teks cron: revisi Langkah 4 (durasi <45 + jangkar bahasa + anti-pangkas-kaku) disiapkan sebagai file untuk diterapkan agen induk.
8. E2E reproduksi data center tanpa publish + laporan QC per klip + frame sheet.
9. Sinkronisasi dokumen: Spec.md/ADJUSTMENTS.md dicatat perubahan aturannya (durasi <45, margin subtitle, QC bahasa).

## Kriteria sukses

- Suite tidak regresi (baseline 285 passed), ruff bersih, frontend hijau bila tersentuh.
- Check durasi membuktikan: naskah estimasi 44 detik LOLOS, 46 detik ERROR, 22 detik LOLOS.
- QC bahasa membuktikan pada tes: klip terdeteksi non-id memicu regenerasi terbatas dan tercatat.
- Reproduksi data center: render < 45 detik, subtitle di posisi baru, laporan QC menunjukkan mayoritas klip terdeteksi "id" (atau hasil undi ulang terbaik), dan **tes dengar pemilik** menyatakan logat cukup konsisten + narasi luwes. Verdict pemilik = penutup fase.

## Di luar cakupan

- Sintesis narasi satu tarikan utuh (single-take) lalu dipotong via alignment — perbaikan struktural anti-drift yang lebih besar; kandidat Fase 12 bila QC + jangkar bahasa belum cukup menurut telinga pemilik.
- Mengganti provider/model TTS.
- Mengubah video test data center yang sudah terjadwal publish (keputusan publish-nya berdiri sendiri; reproduksi E2E fase ini project terpisah tanpa publish).
