# Fase 9 — Benchmark Sukro: teks visual, budget angka, rantai dampak, satu kalimat induk

Keputusan pemilik (2026-10-23): analisa frame-by-frame Short monyet finansial
@sukromonyet `2LZLR-Hnun0` (topik IDENTIK dengan pilot MSCI Tikus Berdasi;
128 dtk, 285.513 views, 9.229 like, 1.200 komentar — analisa lengkap di
`~/workspace/yt-analysis/2LZLR-Hnun0/ANALYSIS.md`). Pemilik memvalidasi 4 gap
"kita kalah di sini". Fase ini menutup keempatnya TANPA mengubah durasi target
(30–45 dtk), aturan satir aman (tanpa nama tokoh/partai asli), dan alur publish.

## Bukti gap (dari DB + prompt pabrik saat ini)

1. **Teks visual nol.** Blok `visual_rules.md`: "Never ask for text, letters,
   numbers, logos, or watermarks inside the image." Semua scene polos;
   teks hanya pernah di-composite di thumbnail (`thumbnail_text.py`).
2. **Angka berserakan, tak divisualkan.** MSCI: 11%, 15%, 2027 — masing-masing
   1x, dieja di VO, visual tanpa label angka. Stimulus: 5 angka / 5 scene.
   Sukro: tepat 3 (132T, -8%, Juni 2027), tiap angka muncul di VO + gambar
   besar + judul/thumbnail.
3. **Script berhenti di institusi.** 10 scene MSCI kita: nol kata rupiah /
   pangan / pensiun. Sukro: 27 dtk rantai sebab-akibat sampai mi, tahu, ayam,
   telur, dana pensiun ("urusannya sama lo apa?").
4. **Judul ≠ hook ≠ thumbnail.** Dia: satu kalimat di 4 lapis. Kita: judul,
   VO scene 1 ("Kabar panas…"), dan teks thumbnail tiga redaksi berbeda.

## Desain

### 1. `keyword_text` per scene + composite lokal saat render
- Skema: `SceneDraft.keyword_text: str | None` (1–3 kata, maks ~18 karakter,
  HURUF BESAR di render) di `domain/llm_outputs.py`; kolom scene baru
  (migrasi 0008, JSON/teks nullable, tanpa backfill wajib — scene lama = None).
- Render: generalisasi `services/thumbnail_text.py` → fungsi
  `draw_keyword_text(image_bytes, text)` (font sama, putih + outline hitam,
  pita atas y≈90–280, auto-shrink). Di `jobs/render.py`, gambar scene
  di-composite SEBELUM ffmpeg bila keyword_text terisi → perintah ffmpeg dan
  plan tidak berubah bentuk; `render_hash_parts` WAJIB memasukkan
  keyword_text per scene (ubah keyword = render ulang, bukan cache basi).
- Prompt gambar: blok `safe_zone`/`image.compose` ditambah "leave the top
  22% clear for a keyword overlay" supaya pita teks tidak menabrak kepala
  maskot (subjek upper-middle). QC frame di E2E memverifikasi ini.
- Aturan AI-gambar tetap: generator TIDAK disuruh menggambar teks
  (menolak/typo — pelajaran thumbnail Fase 7); teks selalu lokal & persis.

### 2. Budget angka (deterministik, `domain/script_rules.run_checks`)
- Ekstraktor angka VO: digit ("11", "2,1", "132") DAN ejaan Indonesia
  ("sebelas", "tiga puluh satu", "sembilan ratus", …) → himpunan angka kunci
  berbeda per script.
- Check baru: >3 angka kunci berbeda = issue error (auto-fix chain dapat
  1x kesempatan memperbaiki, pola Fase 3). Angka yang sama diulang bebas.
- Prompt `script.generate`: penulis mendeklarasikan maks 3 angka kunci di
  `claims_to_verify` (tetap fact_check strict untuk kategori Politik).

### 3. Beat `impact` — rantai dampak wajib (kategori Politik & Kebijakan)
- `SceneDraft.beat` pattern ditambah `impact`. Untuk kategori politik:
  tepat 2 scene beat `impact`, posisi sesudah `main` dan sebelum `cta`,
  satu ke dapur/dompet (harga, gaji, tarif, asap/kesehatan — sesuai topik),
  satu ke tabungan/masa depan (pensiun, kerja, utang, layanan publik).
- `run_checks`: politik tanpa 2 beat impact berurutan di zona itu = error.
- Blok baru `impact_chain.md` + revisi `categories/politics.md`: rantai
  sebab-akibat WAJIB eksplisit (A → B → C → warga), bahasa sehari-hari,
  klaim rantai tetap masuk `claims_to_verify` (fact_check strict tidak
  dilonggarkan — rantai yang tidak terverifikasi = potong, bukan karang).
- Budget kata tetap 70–90: 2 scene impact ≈ 2×8 kata, diambil dari
  memadatkan scene `main`, bukan menambah durasi.

### 4. Satu kalimat induk (judul = hook = thumbnail = frame pertama)
- `hook_rules.md` direvisi: judul ditulis PERTAMA; VO scene 1 (hook) harus
  parafrasa dekat judul — check token-Jaccard ≥0,5 antara `title` dan
  `hook` di `run_checks` (pakai ulang pola Gerbang B Fase 3); judul yang
  lolos aturan TITLE QUALITY 2026-10-22 tetap berlaku (aktor + verba kuat +
  angka/dampak paling konkret).
- `validate.script` prompt: 4 kriteria benchmark ini jadi area penilaian
  eksplisit (keyword coverage, budget angka, rantai impact, keselarasan
  judul-hook) — skor di bawah ambang pada area mana pun = NEEDS_REVISION.
- Sisi agen (cron produksi, di luar repo): Langkah 4B diperluas — selain
  judul + `thumbnail_text`, agen memverifikasi: thumbnail_text = bentuk
  pendek judul, konsep visual scene 1 = konsep thumbnail, dan melaporkan
  3 angka kunci video itu. Checklist, bukan kode.

### 5. Prompt & provider
- Blok baru: `keyword_rules.md` (cara menulis keyword: kata benda/angka
  dampak scene itu, bukan kalimat; contoh MSCI / DIJUAL / PAKAN / PENSIUN).
- Revisi: `visual_rules.md` (larangan teks diganti: "gambar digambar tanpa
  teks; teks kata kunci ditambahkan lokal — sisakan ruang atas"),
  `pacing.md` (zona beat impact), `hook_rules.md`, `image_text.md`
  (selaraskan: teks terencana = keyword_text lokal, bukan di prompt gambar).
- Versi prompt naik (v2) lewat mekanisme prompt_version/seed yang ada;
  FakeLLM provider mengeluarkan keyword_text + beat impact agar dry-run
  dan seluruh suite tetap hijau.
- UI: editor scene menampilkan/mengedit `keyword_text` (pola field
  `emphasis_words` di `api/scripts.py` + panel scene) — teks saja, tanpa
  pratinjau gambar.

## Tugas (TDD, branch `feat/fase-9-benchmark-sukro`)

1. Migrasi 0008 + model + skema SceneDraft (keyword_text, beat impact) + API/UI field.
2. Ekstraktor angka (digit + ejaan) + check budget angka di run_checks + tes.
3. Check beat impact (khusus kategori politik) + check Jaccard judul-hook + tes.
4. `draw_keyword_text` + integrasi render + render hash + tes pixel/komposit.
5. Prompt v2: blok baru & revisi 5 blok + kategori politik + validate.script.
6. FakeLLM + seed prompt + snapshot/tes prompt.
7. Safe-zone atas di image.compose + QC frame E2E.
8. Cron produksi: Langkah 4B+ (verifikasi 4-lapis + lapor 3 angka kunci).
9. E2E pilot: 1 project uji (topik hari itu, TIDAK publish) — render, periksa
   frame: keyword terbaca, tidak menabrak maskot, subtitle tetap aman;
   tes mute (transkrip visual saja harus menceritakan isi); suite penuh
   hijau + ruff + frontend build; commit + push (deploy key aktif).

## Di luar cakupan
- Durasi 60–128 dtk ala Sukro (eksperimen terpisah, keputusan pemilik).
- Menggambar teks lewat generator AI; menyebut nama tokoh/partai asli;
  perubahan alur publish/executor.

## Kriteria berhasil
- Video uji: ≥80% scene punya keyword_text terbaca; ≤3 angka kunci, semua
  angka kunci tampil visual; 2 scene impact hadir; Jaccard judul-hook ≥0,5;
  tes mute lolos oleh penilai manusia (pemilik) pada frame sheet.
- Suite backend ≥222 passed tetap hijau, ruff bersih, frontend build OK.
