from app.services.render_plan import FPS, RenderPlan, RenderScene

FADE_S = 8 / FPS  # crossfade 8 bingkai (Spec §8.4)
HALF_FADE_S = FADE_S / 2


def _escape_filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _zoompan(scene: RenderScene) -> str:
    frames = max(round(scene.duration_s * FPS), 1)
    d = frames
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    if scene.motion == "zoom_in":
        z, x, y = f"1+0.08*on/{d}", center_x, center_y
    elif scene.motion == "zoom_out":
        z, x, y = f"1.08-0.08*on/{d}", center_x, center_y
    elif scene.motion == "pan_left":
        z, x, y = "1.08", f"{center_x}+iw*0.03*(2*on/{d}-1)", center_y
    elif scene.motion == "pan_right":
        z, x, y = "1.08", f"{center_x}-iw*0.03*(2*on/{d}-1)", center_y
    elif scene.motion == "punch_in":
        z, x, y = "if(lt(on,6),1+0.06*on/6,1.06)", center_x, center_y
    else:  # static
        z, x, y = "1", center_x, center_y
    return (
        f"zoompan=z='{z}':x='{x}':y='{y}':d={d}:fps={FPS}:s=1080x1920"
    )


def build_ffmpeg_command(
    plan: RenderPlan,
    *,
    ass_path: str,
    fonts_dir: str,
    output_path: str,
    video_encoder_args: list[str],
) -> list[str]:
    """Argv FFmpeg lengkap dari rencana — murni, tanpa eksekusi (Spec §8.1).

    Crossfade memakai tpad clone di kedua sisi batas agar panjang total
    tetap sama dengan jumlah durasi scene (§8.4).
    """
    args: list[str] = ["ffmpeg", "-y"]
    for scene in plan.scenes:
        # Satu frame gambar saja: zoompan mengembangnya menjadi durasi scene.
        # Memakai -loop justru melipatgandakan panjang (zoompan bekerja per
        # frame masukan).
        args += ["-i", scene.image_path]
        args += ["-i", scene.audio_path]

    filters: list[str] = []
    has_fade = [
        i > 0 and plan.scenes[i].transition_in == "crossfade"
        for i in range(len(plan.scenes))
    ]
    for i, scene in enumerate(plan.scenes):
        img_index = i * 2
        pad = ""
        if i > 0 and has_fade[i]:
            pad += f",tpad=start_mode=clone:start_duration={HALF_FADE_S:.4f}"
        if i + 1 < len(plan.scenes) and has_fade[i + 1]:
            pad += f",tpad=stop_mode=clone:stop_duration={HALF_FADE_S:.4f}"
        filters.append(
            f"[{img_index}:v]scale=2160:3840:force_original_aspect_ratio=increase,"
            f"crop=2160:3840,{_zoompan(scene)}{pad},format=yuv420p,setsar=1[v{i}]"
        )
        aud_index = i * 2 + 1
        start, end = scene.audio_trim
        filters.append(
            f"[{aud_index}:a]atrim=start={start:.3f}:end={end:.3f},"
            f"asetpts=PTS-STARTPTS,apad=whole_dur={scene.duration_s:.3f},"
            f"atrim=0:{scene.duration_s:.3f}[a{i}]"
        )

    # Rangkai video: xfade untuk batas crossfade, concat untuk cut.
    current = "[v0]"
    current_label = "v0"
    for i in range(1, len(plan.scenes)):
        out_label = f"x{i}"
        if has_fade[i]:
            offset = plan.scenes[i].start_s - HALF_FADE_S
            filters.append(
                f"{current}[v{i}]xfade=transition=fade:duration={FADE_S:.4f}:"
                f"offset={offset:.4f}[{out_label}]"
            )
        else:
            filters.append(f"{current}[v{i}]concat=n=2:v=1:a=0[{out_label}]")
        current = f"[{out_label}]"
        current_label = out_label
    if len(plan.scenes) == 1:
        current_label = "v0"

    audio_inputs = "".join(f"[a{i}]" for i in range(len(plan.scenes)))
    filters.append(f"{audio_inputs}concat=n={len(plan.scenes)}:v=0:a=1[acat]")
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
