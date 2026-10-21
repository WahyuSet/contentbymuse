# Fase 5 — Gambar: Rencana Implementasi

> **DISETUJUI pemilik 2026-10-21 19:21 WIB ("gas Fase 5")** — draft riset latar 19:05 ditinjau agen utama dan dijalankan dengan amendemen berikut (dicatat juga di ledger):
> A1. Branch tetap `feat/fase-5-gambar` (konsisten penamaan Indonesia fase sebelumnya); direktori ledger `.superpowers/sdd/fase-5-gambar/`.
> A2. Normalisasi Pillow menjadi satu fungsi murni `app/services/image_normalize.py` yang dipanggil HANDLER untuk semua provider; adapter muse_cli hanya mengembalikan byte mentah + dimensi aktual (satu tempat normalisasi, idempoten).
> A3. Reconcile gambar mengikuti pelajaran review Fase 4: scene dianggap selesai bila hash aset terpilih cocok dengan digest SALAH SATU kandidat yang akan dicoba handler (bukan hanya provider utama).
> A4. Handler mengikuti konvensi kode yang ada: `run_image(job, factory)` (bukan `(job, ctx)`), handler voice Fase 4 adalah pola acuannya.
> A5. PATCH project: `visual_style_id` tak dikenal → 422 `InvalidVisualStyle` (konsisten dengan `InvalidProvider` Fase 4), bukan 404.
> Untuk agen pelaksana: Wajib memakai sub-skill: gunakan superpowers:subagent-driven-development (disarankan) atau superpowers:executing-plans untuk menjalankan rencana ini per task. Langkah memakai kotak centang (`- [ ]`) untuk pelacakan. Gaya UI mengikuti antislop (identitas Fase 1-4) dan komentar kode mengikuti antislop-code.

**Tujuan:** Setiap scene dari script yang disetujui punya gambar 9:16 tersimpan sebagai aset berversi (bisa dilihat dari UI), dirender dari template `image.compose` + Visual Style project, dengan cache `input_hash` dan regenerate per scene — menutup paruh kedua baris Fase 4 di spec §14 ("Semua scene punya suara, timing, dan gambar").

**Arsitektur:** Tabel `visual_style` (gaya + jangkar maskot + gambar referensi opsional) yang dipilih per project; job `image` per scene: compose prompt → cache `input_hash` → generate (router image; fake / muse_cli) → verifikasi Pillow → normalisasi 1080×1920 (scale-to-cover, crop pusat vertikal 40%) → simpan sebagai aset `image` → `select_asset`. Reconcile pasca-Gerbang B mengantrekan `image` untuk scene yang aset terpilihnya tidak ada / hash-nya tidak cocok. `resource_key` = `image:<provider_id>` (batas konkurensi 2, §7).

**Stack teknologi:** yang sudah ada + Pillow (sudah dipakai fake image) + CLI `media-generation` VM untuk adapter `muse_cli`.

## Fakta terverifikasi (riset 2026-10-21, smoke test langsung)

Invokasi CLI yang benar untuk gambar (terverifikasi dua kali generate nyata):

```bash
media-generation --media-subagent-output-type image --orientation vertical \
  --image-output-format jpg --output-dir <dir> --timeout-secs 450 \
  --conversation-json '[{"image": "<ref-path>"}, {"text": "<prompt>"}]'
# tanpa "image" entry bila tidak ada referensi
```

- `--aspect-ratio 9:16` **tidak didukung** untuk operasi ini ("not supported for this media operation"); `--orientation vertical` yang memberi 9:16. Keduanya saling eksklusif.
- `--reference-image-file` adalah argumen **legacy** dan **tidak bisa digabung** dengan jalur media_subagent ("cannot be combined with legacy media-generation arguments"); gambar referensi dikirim lewat entry `{"image": path}` di `--conversation-json` (terverifikasi: generate dengan referensi sukses).
- Output: JSON payload di stdout dengan `media_paths[0]` = path file hasil (juga tertulis di output-dir); nama file `media-generation-<slug>-0-<uuid>.jpg`.
- Hasil aktual: **1152×2048 JPEG RGB** (9:16 tepat, 0.5625) — adapter tetap menormalisasi ke 1080×1920 (scale-to-cover, crop pusat vertikal 40%).
- Latensi terukur: ~50 dtk tanpa referensi, ~32 dtk dengan referensi → `timeout_s` bawaan adapter 600 dtk (konservatif).
- Seed provider mengikuti pola suara (`providers_seed.py`): fake prioritas 100 selalu; `muse_cli` prioritas 20 hanya bila CLI ada di PATH (`shutil.which("media-generation")`).

## Konteks dari Spec (mengikat)

- Baris Fase 4 di §14: "Adapter suara, alignment, adapter gambar, Visual Style, grid scene dengan regenerate dan versi. Selesai bila: Semua scene punya suara, timing, dan gambar." — build ini memecahnya: Fase 4 = suara+alignment (selesai), Fase 5 = gambar+Visual Style (fase ini). Dicatat sebagai Keputusan 1.
- §2.1 project: `image_provider_id` (fk), `visual_style_id` (fk) — "ditambah oleh migrasi fase yang memakainya" → migrasi `0005` fase ini.
- §2.2 `asset`: kind mencakup `image` dan `reference_image` (gambar referensi Visual Style adalah aset global, `project_id` null); versi per (project, scene, kind); `is_selected` tunggal (indeks parsial).
- §2.x `visual_style`: `id, name, version, style_text, negative_text, mascot_anchor, reference_asset_id (null), image_params (JSON), is_default`.
- §4.8 Gambar: satu job `image` per scene (tanpa induk); prompt final dirender dari template `image.compose` dengan input `style_text`, `mascot_anchor` (hanya bila `include_mascot`), `visual_prompt`, `visual_type`, blok zona aman, blok teks Bahasa Indonesia; normalisasi v2 (Fase 6p): spasi berlebih di `style_text` dirapikan, `mascot_anchor` diakhiri tepat satu titik, kalimat garis lantai hanya untuk `visual_type` `character`/`environment`; blok `visual_rules` (subjek berulang ditulis dengan kata yang sama; label ditulis seperti tercetak, mis. "Rp19.900"); blok `mascot` (orang lain = stick figure hitam tanpa kepala hijau); bila provider `supports_reference_image` dan `include_mascot` → gambar referensi Visual Style ikut dikirim; hasil diverifikasi Pillow lalu disesuaikan ke 1080×1920 (diskalakan menutupi bingkai, crop dengan pusat vertikal di 40% tinggi); `retry_safe: false` → `max_attempts = 1`; label fake: `NN visual_type`.
- §4.12 reconcile: untuk script aktif `approved`, scene yang `image` terpilihnya tidak ada → enqueue `image`.
- §4.x (tahap images): satu slot per scene; `ready` bila hash cocok; `stale` bila hash berbeda; `failed` bila job terbaru gagal tanpa aset; tanpa provider → `NoImageProvider`. "Hanya `input_hash` yang menentukan usang."
- §5.1 image: `ImageRequest(prompt, negative_prompt, aspect_ratio="9:16", reference_images, seed, model, extra)`; `ImageResult(image: bytes, mime, width, height, revised_prompt, usage)`; `ImageCaps(supports_reference_image)`.
- §7: `resource_key` `image:<provider_id>`, `quirks.max_concurrency` default 2.
- ADJUSTMENTS.md: adapter `muse_cli` image/video memakai CLI VM ini saja (tidak portabel ke VPS Fase 7); teks di thumbnail di-composite lokal (Pillow/drawtext), bukan digambar AI — itu Fase 6b, di luar lingkup.
- Aturan gambar durable pemilik (MEMORY.md): semua teks dalam gambar Bahasa Indonesia (brand seperti 'Tirexxz' apa adanya); bila tidak ada teks label yang diminta, jangan gambar teks sama sekali; komposisi 9:16 dengan subjek di tengah-atas, seperempat bawah + tepi kanan bebas dari detail penting (tertutup subtitle & tombol aplikasi).

## Keputusan lingkup fase ini

1. **Penomoran**: build memecah Fase 4 spec menjadi Fase 4 (suara, selesai) + Fase 5 (gambar, fase ini). Migrasi `0005` memuat `visual_style`, kolom gambar project, dan seed provider gambar.
2. **muse_cli `supports_reference_image = true`** — berbeda dari spike relay Fase 0 (false); referensi dikirim sebagai entry `{"image": path}` di `--conversation-json` (terverifikasi; `--reference-image-file` legacy tidak kompatibel dengan jalur media_subagent). Dipakai hanya bila `include_mascot` dan style punya `reference_asset_id`.
3. **Referensi default null**: seed `visual_style` bawaan tanpa gambar referensi (`reference_asset_id` null, sesuai spec). Upload/generate gambar referensi = stretch goal; adapter tetap diuji dengan reference bytes yang disuntik.
4. **CLI tidak menerima size eksplisit** (tidak seperti relay `size=1024x1792` di §4.8); normalisasi kode ke 1080×1920 menutupi perbedaan dimensi apa pun.
5. **Cache image** mengikuti §2.4 seperti voice: sebelum memanggil provider, cari aset `image` di project sama dengan `input_hash` sama; ketemu dan tidak `force` → baris aset baru menunjuk `storage_key` yang sama (scene berbeda) atau pakai baris yang ada (scene sama), jadikan terpilih. `force` selalu memanggil provider.
6. **Kegagalan CLI tidak di-retry** (`retryable=False`, pola `voice/muse_cli.py`): generasi baru menghasilkan visual berbeda, mengulang tidak memperbaiki.
7. **Blok zona aman** di `image.compose` mengkodekan aturan durable pemilik: subjek utama di tengah-atas, seperempat bawah + tepi kanan bebas detail penting.
8. **Blok teks Indonesia**: teks dalam gambar hanya Bahasa Indonesia; tanpa label eksak yang diminta → instruksikan tanpa teks sama sekali.

## Konvensi global

- Warisan Fase 1-4: ULID, UTC, `/api`, error standar, pesan Indonesia, TDD, commit per task, ruff bersih, komentar seperlunya (antislop-code).
- Branch `feat/fase-5-gambar` dari ujung `feat/fase-4-voice`. `HANDLERS` bertambah `image`.
- Penyimpanan file hanya lewat `LocalStorage`; kunci aset: `assets/{project_id}/{scene_id}/image-v{version}.jpg`.

---

### Task 1: Migrasi 0005 — visual_style + kolom gambar project + seed provider

**File:**
- Ubah: `backend/app/db/models.py` (+ `VisualStyle`; `Project.image_provider_id`, `Project.visual_style_id`)
- Buat: `backend/alembic/versions/0005_image.py`
- Ubah: `backend/app/services/providers_seed.py` (seed provider image: fake selalu prioritas 100; muse_cli prioritas 20 bila CLI di PATH — deteksi via `shutil.which("media-generation")`)
- Buat: `backend/tests/test_image_seed.py` (atau perluas test seed)

**Antarmuka:**
- `VisualStyle`: `id (ULID str), name, version, style_text, negative_text, mascot_anchor, reference_asset_id (null), image_params (JSON), is_default`.
- Seed satu style bawaan `is_default=true`: `style_text` mendeskripsikan doodle 2D maskot stickman berkepala hijau (konsisten ADJUSTMENTS + karakter visual project); `mascot_anchor` satu kalimat jangkar maskot (diakhiri satu titik); `negative_text` (teks Inggris di gambar, fotorealistik, watermark, ...).
- Project baru → `visual_style_id` = style default (di API create project atau default di kode; pilih satu, konsisten).

- [ ] **Langkah 1: Tes** — migrasi naik/turun bersih di sqlite; seed: fake image selalu ada; muse_cli ada bila `media-generation` di PATH (mock `shutil.which`); style default tepat satu.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-5): visual style + seed provider gambar`

### Task 2: Template image.compose + blok zona aman & teks

**File:**
- Buat: `backend/app/prompts/tasks/image.compose/v1.md`, `backend/app/prompts/blocks/safe_zone.md`, `backend/app/prompts/blocks/image_text.md`
- Ubah: `backend/app/services/prompts.py` (fungsi `compose_image_prompt(style, scene) -> str`; sinkronisasi template baru seperti task lain)
- Buat: `backend/tests/test_image_compose.py`

**Antarmuka:**
- `compose_image_prompt(style: VisualStyle, scene) -> str`: render template dengan `style_text` (spasi berlebih dirapikan), `mascot_anchor` (hanya bila `scene.include_mascot`; pastikan tepat satu titik di akhir), `visual_prompt`, `visual_type` (+ kalimat garis lantai hanya untuk `character`/`environment`), blok `visual_rules` (pakai file blok yang sudah ada), blok `safe_zone` baru, blok `image_text` baru.
- `safe_zone.md`: subjek utama di tengah-atas bingkai 9:16; seperempat bawah dan tepi kanan bebas dari detail penting (area subtitle & tombol aplikasi).
- `image_text.md`: setiap teks yang tampil harus Bahasa Indonesia (ejaan benar); bila scene tidak meminta label teks eksak, gambar tanpa teks sama sekali.

- [ ] **Langkah 1: Tes** — golden test: scene contoh → prompt final memuat keempat blok; `include_mascot=false` → tanpa mascot_anchor; visual_type `object` → tanpa kalimat garis lantai; style_text ber-spasi ganda → rapi.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-5): template image.compose`

### Task 3: Adapter muse_cli image

**File:**
- Buat: `backend/app/providers/image/muse_cli.py`
- Buat: `backend/tests/test_muse_cli_image.py`

**Antarmuka:**
- `class MuseCliImage`: `caps = ImageCaps(supports_reference_image=True)`; `__init__(quirks)` dengan `cli_path` (default `media-generation`) dan `timeout_s` (default 600 — hasil smoke test).
- `async def generate_image(req: ImageRequest, ctx=None) -> ImageResult`: tulis tiap `reference_images` ke file sementara (atau pakai langsung bila sudah path) → susun `--conversation-json` sebagai daftar entry `{"image": path}` + satu `{"text": prompt_final}` → panggil CLI `media-generation --media-subagent-output-type image --orientation vertical --image-output-format jpg --output-dir <tmp> --timeout-secs <n> --conversation-json '<json>'` (prompt di dalam JSON, bukan argv posisi; `negative_prompt` digabung ke teks prompt karena CLI tidak punya flag-nya — catat di docstring); parse stdout JSON → ambil `media_paths[0]`; baca bytes; verifikasi + normalisasi Pillow: buka, konversi RGB, scale-to-cover ke 1080×1920, crop dengan pusat vertikal 40%; kembalikan `ImageResult(image=jpeg_bytes, mime="image/jpeg", width=1080, height=1920, usage=Usage(images=1))`. CLI hilang/timeout/parse gagal/`ok:false` → `ServerError` dengan `retryable=False` (pesan Indonesia, pola `voice/muse_cli.py`).
- Normalisasi Pillow dipisah jadi fungsi murni `normalize_to_1080x1920(raw: bytes) -> bytes` agar bisa diuji tanpa CLI.

- [ ] **Langkah 1: Tes** — normalisasi: input 1024×1792 dan 2048×2048 → selalu 1080×1920, RGB JPEG; CLI dimock (skrip fake `media-generation` di PATH tes menulis file contoh) → bytes kembali + reference diteruskan sebagai flag; CLI exit≠0 → ServerError non-retryable.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-5): adapter image muse_cli`

### Task 4: Job image + cache + aset

**File:**
- Buat: `backend/app/jobs/image.py`; ubah `backend/app/jobs/handlers.py` (+ `image`)
- Buat: `backend/tests/test_image_job.py`

**Antarmuka:**
- `async def run_image(job, ctx)`: muat scene + project + style (project.visual_style_id atau default) → `prompt_final = compose_image_prompt(...)` → `input_hash` = sha256 JSON kanonis `{prompt_final, provider_id, model, reference_asset_id, image_params}` → cache §2.4 (Keputusan 5; `force` melewati cache) → `ProviderRouter.generate_image` dengan `ImageRequest(prompt=prompt_final, aspect_ratio="9:16", reference_images=[bytes referensi] bila caps+include_mascot+ada)` → `normalize_to_1080x1920` untuk hasil non-muse_cli juga (semua provider dinormalisasi di handler, bukan di adapter — kecuali muse_cli yang sudah melakukannya; idempoten) → simpan `LocalStorage` → `add_asset(kind="image", scene_id, version=max+1, mime, width=1080, height=1920, data={"prompt": prompt_final}, input_hash, provider_id, model, job_id)` → `select_asset` → catat `usage_record`.
- Provider image project: `project.image_provider_id` atau kandidat prioritas router (pola `expected_voice` Fase 4 → `expected_image_provider` bila diperlukan reconcile; putuskan saat implementasi, catat).

- [ ] **Langkah 1: Tes** — fake: scene approved → `run_image` → aset image terpilih 1080×1920 + data.prompt; panggil lagi → cached (provider tidak dipanggil dua kali); `force` → versi 2; hash berubah (visual_prompt diedit) → generate baru; `reference_images` diteruskan hanya bila caps mendukung.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-5): job image dan aset`

### Task 5: Reconcile gambar

**File:**
- Ubah: `backend/app/services/reconcile.py` (cabang produksi); perluas `backend/tests/test_production_reconcile.py`

**Antarmuka:**
- Sesudah cabang Gerbang A & finalize, untuk script aktif `approved`: tiap scene (urut posisi): hitung `input_hash` keadaan sekarang (butuh compose prompt — pastikan murah & sinkron); aset terpilih `image` tidak ada / hash beda DAN tidak ada job `image` aktif untuk scene → enqueue `image` input `{"scene_id"}` dengan `resource_key=f"image:{provider_id}"` bila provider diketahui. Tanpa provider image → diam (tahap UI menampilkan `NoImageProvider`, pola voice).

- [ ] **Langkah 1: Tes** — 3 scene tanpa aset → 3 job image terantre dengan resource_key benar; panggil lagi saat aktif → tetap 3; hash cocok → tidak mengantrekan; script belum approved → diam.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-5): reconcile produksi gambar`

### Task 6: API — pin gambar project, visual style, regenerate

**File:**
- Ubah: `backend/app/api/projects.py` (PATCH: `image_provider_id` (validasi capability image → 422), `visual_style_id` (ada → 404 bila tidak)), `backend/app/api/catalog.py` (daftar visual styles bila pola voices dipakai)
- Buat: `backend/app/api/image.py` (atau perluas assets.py): `POST /api/scenes/{scene_id}/image/regenerate` (202; pola voice: scene harus milik script aktif → 409 `ScriptNotActive`; job aktif → `created=false`; selain itu enqueue `force: true` + resource_key)
- Buat: `backend/tests/test_image_api.py`

- [ ] **Langkah 1: Tes API** — PATCH pin tersimpan; provider LLM untuk image ditolak 422; regenerate pada script aktif → job force; script non-aktif → 409; daftar visual styles memuat default.
- [ ] **Langkah 2: RED**.
- [ ] **Langkah 3: Implementasi.**
- [ ] **Langkah 4: Hijau.**
- [ ] **Langkah 5: Commit** — `feat(fase-5): API gambar dan visual style`

### Task 7: UI gambar (antislop)

**File:**
- Ubah: `frontend/src/ProjectDetail.tsx` (blok "Gambar": select provider image + select visual style), `frontend/src/ScriptPanel.tsx` (SceneRow: pratinjau `<img src={url}>` bila ada aset terpilih, tombol "Buat ulang gambar", keadaan "Gambar belum dibuat"/"Sedang dibuat…"), `frontend/src/lib/projects.ts` (tipe kolom gambar), `frontend/src/styles.css`

**Antarmuka & rancangan:**
- Poll aset scene 1 dtk seperti blok suara; semua teks Indonesia; keadaan tidak hanya warna; gaya panel kertas Fase 1-4.

- [ ] **Langkah 1: Tes helper** (bila ada logika murni, mis. label versi) — RED dulu.
- [ ] **Langkah 2: Implementasi.**
- [ ] **Langkah 3: Hijau** — vitest + build.

### Task 8: E2E + review menyeluruh

- [ ] **Langkah 1: E2E hidup** — server bertiga; project cicak yang approved (DB dev) → reconcile/worker memproduksi gambar semua scene via **muse_cli asli** (E2E spesial seperti Fase 4: bukan fake); `GET /scenes/{id}/assets` → image terpilih 1080×1920; `GET /api/files/...` → byte JPEG; satu scene di-regenerate → versi 2 terpilih; cache: hash sama → provider tidak dipanggil dua kali. Catat latensi & dimensi aktual CLI di ledger.
- [ ] **Langkah 2: Suite segar penuh** — backend pytest + ruff; frontend vitest + build.
- [ ] **Langkah 3: Commit** — `feat(fase-5): UI gambar + e2e`.
- [ ] **Langkah 4: Review** — paket diff dari ujung Fase 4 → reviewer subagent fresh dengan Focus review di bawah; perbaiki Critical/Important satu pass TDD; Minor ke ledger `.superpowers/sdd/fase-5-gambar/progress.md`. Perbarui `~/MEMORY.md`.

## Focus review

1. Cache image benar: hash berubah (visual_prompt/style/provider/reference diganti) → gambar baru; hash sama → provider tidak dipanggil; `force` selalu memanggil.
2. `is_selected` tidak pernah ganda per (project, scene, kind) — termasuk `reference_image` global (scene null).
3. Normalisasi 1080×1920 benar untuk input apa pun: scale-to-cover + crop pusat vertikal 40%; bukan stretch; bukan crop tengah.
4. `image.compose` v2: mascot_anchor tepat satu titik di akhir; tanpa anchor bila `include_mascot=false`; kalimat garis lantai hanya untuk `character`/`environment`; blok zona aman & teks Indonesia selalu ada.
5. Reconcile tidak mengantrekan dobel saat job aktif; berhenti setelah hash cocok; hanya untuk script aktif `approved`.
6. `/api/files` untuk gambar memakai `media_type` dari aset (pola Fase 4) — tidak tertukar dengan baris lain yang berbagi file.
7. CLI: prompt dikirim dalam `--conversation-json` via `json.dumps` (bukan shell) dengan `create_subprocess_exec`; `media_paths[0]` dari stdout JSON yang dipakai (bukan tebak nama file); timeout menewaskan proses; file sementara dibersihkan.

## Batas fase (tidak dikerjakan di sini)

- Thumbnail terpisah (Fase 6b spec) — composite teks lokal Pillow/drawtext.
- Mode video AI (Fase 6s) — memakai klip video, bukan gambar ini.
- Render MP4 + subtitle (Fase 5 penomoran lama / render §4.9+§8) — fase berikutnya.
- Upload gambar referensi Visual Style (stretch goal Task 1 bila waktu sisa; jika tidak, jadi utang ledger).
