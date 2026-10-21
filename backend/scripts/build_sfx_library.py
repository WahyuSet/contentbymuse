"""Sintesis perpustakaan SFX bawaan dengan FFmpeg (lisensi bersih, deterministik).

Jalankan: .venv/bin/python scripts/build_sfx_library.py
Menghasilkan WAV mono 44.1kHz di app/assets/sfx/.
"""

import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "sfx"
SR = 44100

# id -> (argumen -i lavfi, rantai -af) ; semua berakhir dipad ke durasi resep.
RECIPES: dict[str, tuple[list[str], str]] = {
    # Denting terang dua nada dengan peluruhan.
    "ding": (
        [f"aevalsrc=(sin(2*PI*1568*t)+0.5*sin(2*PI*2093*t))*exp(-6*t):s={SR}:d=0.5"],
        "apad=whole_dur=0.5",
    ),
    # Dentuman rendah, nada ikut turun.
    "boom": (
        [f"aevalsrc=sin(2*PI*(62-24*t)*t)*exp(-3.5*t):s={SR}:d=0.8"],
        "apad=whole_dur=0.8",
    ),
    # Desis transisi: derau pita dengan amplop naik-turun.
    "whoosh": (
        [f"anoisesrc=color=white:duration=0.45:sample_rate={SR}"],
        "bandpass=f=900:width_type=h:w=1.2,"
        "aeval=val(0)*sin(3.14159*t/0.45):c=same,apad=whole_dur=0.45",
    ),
    # Letupan pendek.
    "pop": (
        [f"aevalsrc=sin(2*PI*500*t)*exp(-30*t):s={SR}:d=0.12"],
        "apad=whole_dur=0.12",
    ),
    # Denting koin: dua nada tinggi cepat.
    "cash": (
        [f"aevalsrc=(sin(2*PI*2093*t)*exp(-9*t)"
         f"+0.7*sin(2*PI*2637*t)*exp(-11*t)):s={SR}:d=0.35"],
        "apad=whole_dur=0.35",
    ),
    # Meluncur turun (komedi jatuh/anjlok): sapuan 800 -> 250 Hz.
    "fall": (
        [f"aevalsrc=sin(2*PI*(800*t-550*t*t))*exp(-1.2*t):s={SR}:d=0.6"],
        "apad=whole_dur=0.6",
    ),
    # Sting perkusi pendek penanda punchline.
    "drum": (
        [f"anoisesrc=color=white:duration=0.3:sample_rate={SR}"],
        "aeval=val(0)*exp(-14*t):c=same,lowpass=f=900,apad=whole_dur=0.3",
    ),
    # Gesekan piringan (record scratch) untuk kejutan.
    "scratch": (
        [f"anoisesrc=color=pink:duration=0.4:sample_rate={SR}"],
        "highpass=f=1200,aeval=val(0)*(0.4+0.6*sin(50*t))*exp(-3*t):c=same,"
        "apad=whole_dur=0.4",
    ),
    # Kilau naik untuk momen positif: sapuan 1200 -> 1800 Hz.
    "sparkle": (
        [f"aevalsrc=sin(2*PI*(1200*t+300*t*t))*exp(-4*t):s={SR}:d=0.5"],
        "apad=whole_dur=0.5",
    ),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sfx_id, (source, chain) in RECIPES.items():
        target = OUT / f"{sfx_id}.wav"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", source[0],
                "-af", chain,
                "-ar", str(SR), "-ac", "1",
                str(target),
            ],
            check=True,
        )
        print("sfx:", target.name, target.stat().st_size, "byte")


if __name__ == "__main__":
    main()
