from app.services.render_plan import FPS, RenderPlan, RenderScene

FADE_S = 0.35  # Fase 13: crossfade 0,35 dtk di semua batas (dulu 8 frame)
HALF_FADE_S = FADE_S / 2
ZOOM = 0.22  # Fase 13: zoom 22% (dulu 8%) — gerakan harus terasa, bukan pelan
PAN_SWEEP = 0.05


def _escape_filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _zoompan(scene: RenderScene) -> str:
    frames = max(round(scene.duration_s * FPS), 1)
    d = frames
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    if scene.motion == "zoom_in":
        z, x, y = f"1+{ZOOM}*on/{d}", center_x, center_y
    elif scene.motion == "zoom_out":
        z, x, y = f"{1 + ZOOM}-{ZOOM}*on/{d}", center_x, center_y
    elif scene.motion == "pan_left":
        z, x, y = f"{1 + ZOOM}", f"{center_x}+iw*{PAN_SWEEP}*(2*on/{d}-1)", center_y
    elif scene.motion == "pan_right":
        z, x, y = f"{1 + ZOOM}", f"{center_x}-iw*{PAN_SWEEP}*(2*on/{d}-1)", center_y
    elif scene.motion == "punch_in":
        # Fase 13: menghentak cepat di 12 frame pertama lalu tahan.
        z, x, y = "if(lt(on,12),1+0.15*on/12,1.15)", center_x, center_y
    else:  # static
        z, x, y = "1", center_x, center_y
    return (
        f"zoompan=z='{z}':x='{x}':y='{y}':d={d}:fps={FPS}:s=1080x1920"
    )


def _shake_gate(scene, plan) -> str | None:
    """Ekspresi 0/1 untuk jendela goyang scene ini (0,4 dtk sejak tiap kata
    pemicu cue SFX). None bila scene tidak punya cue."""
    windows = []
    for ev in plan.sfx_events:
        if ev.kind != "cue":
            continue
        if scene.start_s <= ev.at_s < scene.start_s + scene.duration_s:
            c0 = round(ev.at_s - scene.start_s, 3)
            windows.append(f"between(t,{c0},{round(c0 + 0.4, 3)})")
    if not windows:
        return None
    gate = windows[0]
    for extra in windows[1:]:
        gate = f"max({gate},{extra})"
    return gate


def build_ffmpeg_command(
    plan: RenderPlan,
    *,
    ass_path: str,
    fonts_dir: str,
    output_path: str,
    video_encoder_args: list[str],
    keyword_paths: dict[int, str] | None = None,
) -> list[str]:
    """Argv FFmpeg lengkap dari rencana — murni, tanpa eksekusi (Spec §8.1).

    Fase 13: semua batas scene memakai xfade (fade; slideleft masuk scene
    twist) dengan tpad clone di kedua sisi agar panjang total tetap sama
    dengan jumlah durasi scene. Keyword text di-overlay animasi (bukan
    ditempel statis), scene bercue SFX digoyang kameranya.
    """
    keyword_paths = keyword_paths or {}
    args: list[str] = ["ffmpeg", "-y"]
    for scene in plan.scenes:
        # Satu frame gambar saja: zoompan mengembangnya menjadi durasi scene.
        # Memakai -loop justru melipatgandakan panjang (zoompan bekerja per
        # frame masukan).
        args += ["-i", scene.image_path]
        args += ["-i", scene.audio_path]
    kw_index: dict[int, int] = {}
    next_input = len(plan.scenes) * 2
    for i, scene in enumerate(plan.scenes):
        if i in keyword_paths:
            kw_index[i] = next_input
            next_input += 1
            args += [
                "-loop", "1", "-t", f"{scene.duration_s:.3f}",
                "-i", keyword_paths[i],
            ]
    from app.services import sfx_catalog

    sfx_base = next_input
    for event in plan.sfx_events:
        args += ["-i", str(sfx_catalog.sfx_path(event.sfx_id))]

    filters: list[str] = []
    for i, scene in enumerate(plan.scenes):
        img_index = i * 2
        filters.append(
            f"[{img_index}:v]scale=2160:3840:force_original_aspect_ratio=increase,"
            f"crop=2160:3840,{_zoompan(scene)},format=yuv420p,setsar=1,"
            f"settb=AVTB[v{i}raw]"
        )
        cur = f"v{i}raw"
        if i in kw_index:
            filters.append(
                f"[{kw_index[i]}:v]format=rgba,fade=t=in:st=0:d=0.3:alpha=1[kwf{i}]"
            )
            filters.append(
                f"[{cur}][kwf{i}]overlay="
                f"x='(W-w)/2+60*max(0,1-t/0.3)':y=90:shortest=1[v{i}kw]"
            )
            cur = f"v{i}kw"
        gate = _shake_gate(scene, plan)
        if gate is not None:
            filters.append(
                f"[{cur}]scale=1140:2028,"
                f"crop=1080:1920:"
                f"x='30+12*sin(2*PI*18*t)*{gate}':"
                f"y='54+12*cos(2*PI*18*t)*{gate}'[v{i}sh]"
            )
            cur = f"v{i}sh"
        pad = ""
        if i > 0:
            pad += f",tpad=start_mode=clone:start_duration={HALF_FADE_S:.4f}"
        if i + 1 < len(plan.scenes):
            pad += f",tpad=stop_mode=clone:stop_duration={HALF_FADE_S:.4f}"
        if pad:
            filters.append(f"[{cur}]{pad[1:]}[v{i}]")
        else:
            filters.append(f"[{cur}]null[v{i}]")
        aud_index = i * 2 + 1
        start, end = scene.audio_trim
        filters.append(
            f"[{aud_index}:a]atrim=start={start:.3f}:end={end:.3f},"
            f"asetpts=PTS-STARTPTS,apad=whole_dur={scene.duration_s:.3f},"
            f"atrim=0:{scene.duration_s:.3f}[a{i}]"
        )

    # Rangkai video: xfade di semua batas (fade; slideleft masuk twist).
    current = "[v0]"
    current_label = "v0"
    for i in range(1, len(plan.scenes)):
        out_label = f"x{i}"
        trans = "slideleft" if plan.scenes[i].beat == "twist" else "fade"
        offset = plan.scenes[i].start_s - HALF_FADE_S
        filters.append(
            f"{current}[v{i}]xfade=transition={trans}:duration={FADE_S:.4f}:"
            f"offset={offset:.4f}[{out_label}]"
        )
        current = f"[{out_label}]"
        current_label = out_label
    if len(plan.scenes) == 1:
        current_label = "v0"

    audio_inputs = "".join(f"[a{i}]" for i in range(len(plan.scenes)))
    filters.append(f"{audio_inputs}concat=n={len(plan.scenes)}:v=0:a=1[acat]")
    if plan.sfx_events:
        # Event SFX ditunda ke waktu globalnya lalu dicampur di bawah narasi;
        # loudnorm tetap tahap terakhir agar level akhir konsisten.
        mix_labels = ["[acat]"]
        base_index = sfx_base
        for k, event in enumerate(plan.sfx_events):
            delay_ms = round(event.at_s * 1000)
            filters.append(
                f"[{base_index + k}:a]aformat=sample_rates=48000:"
                f"channel_layouts=stereo,adelay={delay_ms}|{delay_ms},"
                f"volume={event.gain:.2f}[sfx{k}]"
            )
            mix_labels.append(f"[sfx{k}]")
        # Redam narasi sesaat di tiap titik potong scene (turun ke 0.45 pada
        # jendela -0.05..+0.35 dtk di sekitar batas) supaya whoosh transisi
        # terdengar menonjol; tanpa ini whoosh tertutup narasi yang mengalir.
        cuts = [s.start_s for s in plan.scenes[1:]]
        if cuts:
            expr = "*".join(
                f"if(between(t,{c - 0.05:.3f},{c + 0.35:.3f}),0.45,1)"
                for c in cuts
            )
            filters.append(f"[acat]volume=volume='{expr}':eval=frame[adip]")
            filters.append(
                "[adip]aformat=sample_rates=48000:channel_layouts=stereo[acatf]"
            )
        else:
            filters.append(
                "[acat]aformat=sample_rates=48000:channel_layouts=stereo[acatf]"
            )
        mix_labels[0] = "[acatf]"
        filters.append(
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:"
            f"duration=first:normalize=0[amix]"
        )
        filters.append("[amix]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    else:
        filters.append("[acat]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    filters.append(
        f"[{current_label}]ass=filename='{_escape_filter_path(ass_path)}'"
        f":fontsdir='{_escape_filter_path(fonts_dir)}'[vout]"
    )

    args += ["-filter_complex", ";".join(filters)]
    args += ["-map", "[vout]", "-map", "[aout]"]
    args += video_encoder_args
    args += [
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        output_path,
    ]
    return args
