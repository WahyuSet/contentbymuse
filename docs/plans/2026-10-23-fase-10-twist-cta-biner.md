# Fase 10 — Twist + CTA Biner (Benchmark Sukro, lanjutan Fase 9)

Status: PLAN — menunggu persetujuan pemilik untuk dibangun.
Tanggal: 2026-10-23. Cabang usulan: `feat/fase-10-twist-cta` dari ujung `feat/fase-9-benchmark-sukro`.

## Kenapa fase ini ada

Fase 9 mengunci 2 dari 4 pola pemenang Sukro (teks keyword visual + budget angka + rantai impact + satu kalimat induk). Dua pola sisanya baru terbukti dari analisa video ke-2 dan ke-3, setelah Fase 9 selesai:

| Video | Durasi | Views | Like | Komen | Twist | CTA biner |
|---|---|---|---|---|---|---|
| Gas merah putih (HK9XxZoIikU, Jul 2026) | 99s | 507k | **4,01%** | **0,59%** | ✅ | ✅ |
| MSCI (2LZLR-Hnun0, 17 Okt 2026) | 128s | 285k | 3,23% | 0,42% | ❌ | ❌ |
| Data center (p9mKhZkSacU, 11 Okt 2026) | 110s | 241k | 2,40% | 0,28% | ❌ | ❌ |

Video data center adalah kasus kontrol: kualitas gambar/riset setara, durasi setara, topik panas — tapi struktur lurus tanpa twist, CTA generik ("menurut lu gimana?"), taruhan abstrak → engagement separuh video gas. Analisa lengkap: `~/workspace/yt-analysis/HK9XxZoIikU/ANALYSIS.md` dan `~/workspace/yt-analysis/p9mKhZkSacU/ANALYSIS.md`.

Dua pola yang dikunci fase ini:

1. **Twist** — hook menyampaikan KLAIM POPULER (yang penonton kira benar, seringnya versi headline/klaim resmi), lalu satu scene di tengah mengoreksinya secara eksplisit. Contoh gas: hook "katanya 30% lebih murah, hemat dong?" → twist di ~50%: "bagian yang paling penting dan sering salah pahami… murahnya itu bukan buat lo — yang turun 30% itu beban subsidi negara, harga rumah tangga tetap." Koreksi ditandai penanda bahasa yang jelas (ternyata / padahal / faktanya / bukan buat…). Menyertai twist: **segmen adil** — satu kalimat mensteelman sisi masuk akal kebijakan ("tapi biar adil, ini tetap masuk akal") sebelum kritik, supaya posisi video dua sisi.
2. **CTA biner** — scene penutup adalah pertanyaan dua pilihan berlawanan yang bisa dijawab ≤5 kata ("langkah cerdas hemat subsidi ATAU cuma ganti kemasan doang?"), bukan pertanyaan terbuka. Pertanyaan yang sama tampil di deskripsi metadata.

## Desain

### Beat baru: `twist`

- Tambah `"twist"` ke himpunan beat (`backend/app/api/scripts.py` `BEATS = {"hook","setup","main","impact","payoff","cta","loop"}`) dan ke semua enumerasi beat lain (skema scene bila ada, daftar beat frontend, fixture FakeLLM, tes). Implementor wajib `grep -rn '"payoff"'` / `grep -rn 'BEATS'` untuk menemukan semua tempat.
- Urutan kanonik kategori politik menjadi:
  `hook (klaim populer) → setup/main (konteks & masalah) → twist (koreksi) → impact ×2 → cta (biner)`
- Alokasi scene format kita (~10 scene, 30–40 dtk): hook 1, setup/main 3–4, twist 1, impact 2, cta 1, sisa payoff/main. Twist muat tanpa memperpanjang durasi.

### Cek deterministik baru di `domain/script_rules.run_checks`

Mengikuti pola cek `impact_chain` Fase 9 (severity & pesan Bahasa Indonesia, `category_slug == "politics"`):

1. `twist_structure` — **error**, khusus politik:
   - Tepat 1 scene beat `twist`.
   - Posisi: sesudah minimal satu scene `main`, dan sebelum scene `impact` pertama (cek impact yang ada tetap tidak berubah; kedua cek harus sama-sama lolos).
   - Narasi scene twist mengandung ≥1 penanda koreksi dari daftar: `ternyata`, `padahal`, `sebetulnya`, `faktanya`, `salah paham`, `bukan buat`, `justru`, `bukan begitu`. Tanpa penanda = error ("koreksi harus eksplisit, bukan tersirat").
2. `binary_cta` — **error** untuk politik, **warning** untuk kategori lain:
   - Berlaku pada scene terakhir bila beat-nya `cta`/`loop`.
   - Narasi mengandung `?` dan kata ` atau `; sisi kiri dan kanan `atau` masing-masing ≥2 kata; kedua sisi tidak identik.
   - Gagal bila penutup hanya pertanyaan terbuka generik (tanpa `atau`) — pesan error menunjuk formula biner.
3. `fairness_marker` — **warning**, khusus politik, hanya bila twist ada:
   - Salah satu scene dari scene twist sampai sebelum scene impact pertama mengandung penanda keadilan: `biar adil`, `adilnya`, `masuk akal`, `sisi baiknya`, `untungnya`. Tidak ada = warning (tidak memblokir; keputusan sadar: steelman kadang menyatu di kalimat twist itu sendiri — validasi LLM yang menilai kualitasnya).

Klaim twist tetap fakta: koreksinya adalah klaim faktual → wajib masuk `claims_to_verify` seperti rantai impact (fact_check strict TIDAK dilonggarkan; twist yang mengarang koreksi = gagal Gate-B seperti biasa). Aturan satir tidak berubah: koreksi menyasar klaim/kebijakan/peran, tidak menyebut nama tokoh/partai asli.

### Prompt v3

- Blok baru `blocks/twist_rules.md`: formula twist (hook = klaim populer versi headline; koreksi eksplisit berpenanda; satu kalimat adil; koreksi = klaim terverifikasi, bukan karangan), dengan contoh gas merah putih sebagai pola (bukan untuk disalin topiknya).
- Blok baru `blocks/cta_rules.md`: formula CTA biner (dua penilaian berlawanan atas kebijakan yang sama, masing-masing ≤5 kata, bisa dijawab tanpa mikir; dilarang "menurut lo gimana?" sebagai satu-satunya penutup; pertanyaan biner = pertanyaan yang sama di deskripsi).
- `blocks/hook_rules.md` direvisi: hook politik kini ditulis sebagai klaim populer yang nanti dikoreksi twist — tetap title-first dan satu kalimat induk (cek Jaccard judul↔hook Fase 9 tidak berubah; judul boleh berbentuk klaim populernya).
- `categories/politics.md`: tambahkan paragraf kewajiban twist + CTA biner, sejajar paragraf rantai impact yang sudah ada.
- Task prompt naik versi (file baru, pola v1.md/v2.md yang ada):
  - `script.generate/v3.md`, `script.fix/v3.md`, `script.revise/v3.md`: include dua blok baru.
  - `validate.script/v3.md`: kriteria benchmark ditambah — (a) twist benar-benar mengoreksi klaim hook (bukan sekadar informasi baru), (b) kalimat adil hadir dan tulus (bukan basa-basi), (c) CTA benar-benar biner: dua sisi adalah penilaian berlawanan yang sama-sama masuk akal dipilih penonton.
  - `metadata.generate/v2.md`: pertanyaan di deskripsi WAJIB pertanyaan biner yang sama dengan scene penutup script (bukan pertanyaan baru).

### FakeLLM

Fixture politik diperbarui: sisipkan scene twist berpenanda + kalimat adil, scene penutup diganti pertanyaan biner. Semua invarian Fase 9 harus tetap lolos (impact tepat 2 sesudah main & sebelum penutup, budget angka ≤3, Jaccard judul↔hook ≥0,5, keyword 10/10). Rantai auto-generate FakeLLM (generate→checks→validate) harus tetap PASS tanpa revisi.

### Frontend

Dropdown beat di editor scene menambah opsi `twist` (label "Twist / Koreksi"). Bila ada pemetaan label/warna beat, samakan polanya dengan beat lain yang sudah ada.

### Cron produksi (diterapkan agen induk, bukan build)

- `tikus-daily-production` Langkah 4 ditambah **Langkah 4C**: saat menimpa scene proyek politik — hook ditulis sebagai klaim populer; tepat 1 scene beat `twist` sesudah scene main terakhir dan sebelum impact pertama, narasinya mengandung penanda koreksi eksplisit dan satu kalimat adil; scene penutup adalah pertanyaan biner. Berlaku juga untuk produksi slot ekstra atas perintah pemilik.
- Verifikasi 4B+ naik dari 4 lapis menjadi **5 lapis**: lapis kelima memeriksa pasangan klaim↔koreksi (hook menyatakan klaim populer, scene twist mengoreksinya) dan penutup (pertanyaan biner yang sama dengan pertanyaan di deskripsi metadata).
- Laporan produksi wajib memuat **7 bukti** (sebelumnya 5): bertambah (6) kalimat twist verbatim dan (7) pertanyaan biner penutup verbatim.

## Tugas (TDD, satu commit per tugas)

1. **Beat `twist` di skema** — tambahkan ke `BEATS` (api/scripts.py) dan semua enumerasi beat lain (grep `"payoff"`/`BEATS` untuk menemukannya: skema scene, fixture, frontend disiapkan di Tugas 8); tes: PATCH scene dengan beat `twist` diterima, beat tak dikenal tetap ditolak. Tanpa migrasi (kolom beat string bebas — verifikasi dulu).
2. **Cek `twist_structure`** — di `run_checks`, mengikuti pola `impact_chain`; tes positif/negatif: tanpa twist, twist ganda, twist sebelum main, twist sesudah impact, twist tanpa penanda koreksi, non-politik tidak terpengaruh.
3. **Cek `binary_cta` + `fairness_marker`** — tes: penutup biner sah lolos; "Menurut lo gimana?" gagal (error di politik, warning di kategori lain); sisi `atau` terlalu pendek gagal; penanda adil hilang → warning `fairness_marker`.
4. **Blok prompt baru + revisi** — `twist_rules.md`, `cta_rules.md`, revisi `hook_rules.md` dan `categories/politics.md`; tes konten prompt dirender memuat penanda kedua blok.
5. **Prompt task v3 + metadata v2** — file versi baru untuk script.generate/fix/revise, validate.script (3 kriteria benchmark baru), metadata.generate (pertanyaan deskripsi = CTA biner penutup); tes versi aktif + konten kriteria. Bila ada tes lama yang mematok versi aktif validate.script == 2, sesuaikan assert versinya (supersesi disengaja, isi kriteria lama tetap di-assert).
6. **FakeLLM selaras** — fixture politik memuat scene twist berpenanda + kalimat adil + penutup biner; deskripsi metadata memuat pertanyaan biner yang sama; tes rantai kering lolos semua cek (lama + baru) dan validasi PASS.
7. **Teks cron Langkah 4C** — siapkan teks final siap terapkan (file di `.superpowers/sdd/fase-10-twist-cta/langkah-4c-final.md`); build TIDAK menyentuh cron, agen induk menerapkan setelah kode terbukti.
8. **Frontend** — opsi beat "Twist / Koreksi" di editor scene; vitest + build hijau.
9. **E2E pilot tanpa publish** — proyek politik topik baru terverifikasi dengan klaim populer yang bisa di-twist; pin voice_provider_id + voice_id Aria; rantai penuh sampai render; frame sheet untuk QC visual; transkrip verbatim (hook, twist, adil, CTA) dilaporkan ke pemilik untuk "tes baca". Kontrol negatif wajib: salinan scene tanpa twist → error `twist_structure`; salinan penutup generik → error `binary_cta` (output nyata disimpan). Keamanan publish: patuhi gerbang slot live (jangan restart saat ada record `uploading`) dan netralkan record publish proyek uji begitu muncul; keadaan akhir awaiting global harus bersih dari proyek uji.

## Kriteria sukses

- Semua cek baru terbukti menolak pelanggaran (kontrol negatif dengan output nyata), bukan hanya menerima yang benar.
- Suite tidak regresi: backend ≥285 passed (baseline 264 + tes baru), ruff bersih, frontend vitest + build OK. Tanpa migrasi baru.
- Pilot: validasi PASS, `run_checks` 0 error, render 30–40 dtk 1080×1920, keyword 10/10, angka kunci VO ≤3, metadata deskripsi memuat pertanyaan biner penutup.
- Pemilik menjalankan "tes baca" atas transkrip pilot: hook terbaca sebagai klaim populer, twist terbaca sebagai koreksinya, penutup terbaca sebagai dua pilihan. Verdict pemilik = penutup fase.

## Di luar cakupan

- Eksperimen durasi 60–90 dtk (keputusan pemilik terpisah).
- Hardening approve-time re-check untuk jalur timpa scene (utang teknis lama, perintah terpisah).
- CTA biner di `fb_caption` (fase ini hanya deskripsi YouTube); pola FB dinilai setelah data produksi berjalan.

---

*Catatan perbaikan dokumen (2026-10-23 malam): file plan ini awalnya terpotong di tengah bagian Frontend saat penulisan pertama (ekor dokumen hilang, terdeteksi koordinator build dan dicatat di ledger `.superpowers/sdd/fase-10-twist-cta/progress.md`). Bagian dari "### Cron produksi" sampai akhir dokumen ini ditulis ulang persis sesuai desain yang dieksekusi build (Tugas 1–9 dan ruling koordinator R1–R7), agar repo menyimpan plan yang utuh.*