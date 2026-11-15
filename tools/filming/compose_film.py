"""Repeatable, local-only MetaEvolution Rescue film edit from native PNG frames.

No project source or input frame is changed. Every render owns a new directory.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1920, 1080
SAMPLE_RATE = 48000
FRAME_NAME = re.compile(r"frame-(\d{6})\.png\Z")


@dataclass(frozen=True)
class Shot:
    id: str
    frames: Path
    first: int
    count: int
    fps: int
    kicker: str
    title: str
    subtitle: str
    provenance: str
    title_seconds: float

    @property
    def seconds(self):
        return self.count / self.fps


def number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return float(value)


def load_spec(path):
    path = Path(path).resolve(strict=True)
    spec = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(spec, dict):
        raise ValueError("The edit must be a JSON object")
    fps = spec.get("fps", 30)
    if type(fps) is not int or fps not in (24, 25, 30, 50, 60):
        raise ValueError("fps must be 24, 25, 30, 50, or 60")
    if not isinstance(spec.get("shots"), list) or not spec["shots"]:
        raise ValueError("shots must be a nonempty list")
    shots, seen = [], set()
    for row in spec["shots"]:
        if not isinstance(row, dict):
            raise ValueError("Each shot must be an object")
        identity = row.get("id", "")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity):
            raise ValueError("Shot id must contain 1..64 letters, digits, underscores, or hyphens")
        if identity in seen:
            raise ValueError("Duplicate shot id: " + identity)
        seen.add(identity)
        source = row.get("frames")
        if not isinstance(source, str) or not source:
            raise ValueError(identity + ": frames must be a directory path")
        folder = Path(source)
        if not folder.is_absolute():
            folder = path.parent / folder
        folder = folder.resolve(strict=True)
        if not folder.is_dir():
            raise ValueError(identity + ": frames is not a directory")
        indices = sorted(int(match.group(1)) for frame in folder.glob("frame-*.png")
                         if (match := FRAME_NAME.fullmatch(frame.name)))
        if not indices or indices != list(range(indices[-1] + 1)):
            raise ValueError(identity + ": frame sequence must be contiguous and start at 000000")
        start = number(row.get("start", 0), identity + ".start")
        end = number(row.get("end", len(indices) / fps), identity + ".end")
        if end > len(indices)/fps + 1e-9 or start >= end:
            raise ValueError(identity + ": requested frame range is empty or exceeds the source")
        first, last = round(start * fps), round(end * fps)
        if not 0 <= first < last <= len(indices):
            raise ValueError(identity + ": requested frame range is empty or exceeds the source")
        texts = {}
        for key in ("kicker", "title", "subtitle", "provenance"):
            value = row.get(key, "")
            if not isinstance(value, str) or len(value) > 240:
                raise ValueError(identity + ": " + key + " must be text of at most 240 characters")
            texts[key] = value
        title_seconds = number(row.get("title_seconds", min(5.5, (last-first)/fps)), identity + ".title_seconds")
        shot = Shot(identity, folder, first, last-first, fps, **texts, title_seconds=title_seconds)
        shots.append(shot)
    return spec, shots


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def font(size, *, bold=False):
    candidates = ([Path("C:/Windows/Fonts/seguisb.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")]
                  if bold else [Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/arial.ttf")])
    candidates += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    raise FileNotFoundError("A Cyrillic-capable Segoe UI, Arial, or DejaVu Sans font is required")


def fit_font(draw, text, size, width, *, bold=False, minimum=24):
    while size > minimum:
        face = font(size, bold=bold)
        if draw.textlength(text, font=face) <= width:
            return face
        size -= 1
    face = font(minimum, bold=bold)
    if draw.textlength(text, font=face) > width:
        raise ValueError("Title is too long for the safe area: " + text)
    return face


def wrap(draw, text, face, width):
    lines, current = [], ""
    for word in text.split():
        proposed = (current + " " + word).strip()
        if draw.textlength(proposed, font=face) <= width:
            current = proposed
        else:
            if not current:
                raise ValueError("Word is too long for the safe area: " + word)
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def title_panel(shot, output):
    """Transparent text panel; native pixels remain the main subject."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(canvas)
    # A gentle lower gradient protects Cyrillic text without a large UI card.
    for y in range(690, 1007):
        alpha = round(150 * ((y-690)/317)**1.5)
        draw.line((0, y, WIDTH, y), fill=(8, 17, 22, alpha))
    amber, white, secondary = (242, 171, 92, 255), (245, 248, 247, 255), (201, 216, 216, 255)
    x = 102
    if shot.kicker:
        draw.rectangle((x, 784, x+38, 787), fill=amber)
        draw.text((x+55, 767), shot.kicker, font=font(22, bold=True), fill=amber)
    if shot.title:
        face = fit_font(draw, shot.title, 62, 1710, bold=True)
        draw.text((x, 805), shot.title, font=face, fill=white, stroke_width=1, stroke_fill=(0, 0, 0, 80))
    if shot.subtitle:
        face = font(27)
        lines = wrap(draw, shot.subtitle, face, 1580)
        if len(lines) > 2:
            raise ValueError("Subtitle exceeds two lines: " + shot.id)
        for line_number, line in enumerate(lines):
            draw.text((x+1, 888+line_number*34), line, font=face, fill=secondary)
    canvas.save(output)


def persistent_panel(shot, output):
    canvas = Image.new("RGBA", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH, 70), fill=(5, 12, 17, 255))
    draw.rectangle((0, 1007, WIDTH, HEIGHT), fill=(5, 12, 17, 255))
    draw.rectangle((78, 29, 88, 40), fill=(237, 161, 77, 255))
    draw.text((102, 18), "METAEVOLUTION  /  RESCUE", font=font(21, bold=True), fill=(230, 237, 236, 255))
    label = shot.provenance or "КАДРЫ ПРОЕКТА · UNREAL ENGINE"
    face = fit_font(draw, label, 18, 760, minimum=14)
    box = draw.textbbox((0, 0), label, font=face)
    draw.text((WIDTH-100-(box[2]-box[0]), 22), label, font=face, fill=(133, 158, 162, 255))
    draw.text((101, 1030), "РАЗВЕДКА  /  ПОИСК  /  ЭВАКУАЦИЯ", font=font(17), fill=(111, 139, 144, 255))
    draw.text((1600, 1028), "MetaEvolution Rescue", font=font(17), fill=(126, 151, 153, 255))
    canvas.save(output)


def title_fade_filter(shot):
    """Fade only the lower title panel; keep provenance and native pixels stable."""
    end_frame = min(round(shot.title_seconds*shot.fps), shot.count)
    # Sub-frame titles cannot contain a visible fade sample. Treat them as
    # disabled, avoiding zero/negative FFmpeg durations for very short edits.
    if end_frame <= 1:
        return "[graded]null[titled];"
    start_frame = min(round(.25*shot.fps), int(end_frame*.15))
    fade_frames = min(round(.25*shot.fps), (end_frame-start_frame)//2)
    return (
        f"[1:v]format=rgba,fade=t=in:s={start_frame}:n={fade_frames}:alpha=1,"
        f"fade=t=out:s={end_frame-fade_frames}:n={fade_frames}:alpha=1[titlefade];"
        f"[graded][titlefade]overlay=0:0:enable='lte(t,{end_frame/shot.fps:.9f})'[titled];"
    )


def run(command, log):
    with Path(log).open("w", encoding="utf-8") as stream:
        result = subprocess.run([str(value) for value in command], stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = Path(log).read_text(encoding="utf-8", errors="replace")[-4500:]
        raise RuntimeError(f"Command failed (exit {result.returncode}); {log}\n{tail}")


def synthesize_score(path, seconds, boundaries=()):
    """Original procedural stereo score; no samples, quotations, or external music."""
    total = round(number(seconds, "soundtrack duration", .01) * SAMPLE_RATE)
    rng = np.random.default_rng(112026)
    maximum, square_sum = 0.0, 0.0
    beat = 60/86
    with wave.open(str(path), "wb") as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(SAMPLE_RATE)
        for first in range(0, total, SAMPLE_RATE):
            count = min(SAMPLE_RATE, total-first)
            t = (first + np.arange(count, dtype=np.float64)) / SAMPLE_RATE
            progress = t/seconds
            attack, release = min(3.5, seconds*.15), min(5, seconds*.25)
            envelope = np.minimum(1, t/attack) * np.minimum(1, (seconds-t)/release)
            # A pedal note anchors the first movement; brighter fifths resolve it.
            resolve = np.clip((progress-.68)/.2, 0, 1)
            left = .067*np.sin(2*np.pi*41.2034*t) + .031*np.sin(2*np.pi*82.4069*t+.4)
            right = .067*np.sin(2*np.pi*41.2034*t+.04) + .031*np.sin(2*np.pi*82.4069*t+.49)
            pulse = .7 + .3*np.sin(2*np.pi*t/(8*beat))**2
            for harmonic, frequency in enumerate((123.4708, 164.8138, 246.9417, 329.6276)):
                amplitude = .026/(1+harmonic*.6)
                shimmer = .7+.3*np.sin(2*np.pi*t/(13.4+harmonic*2)+harmonic)
                left += amplitude*pulse*shimmer*np.sin(2*np.pi*(frequency-.07)*t+harmonic)
                right += amplitude*pulse*shimmer*np.sin(2*np.pi*(frequency+.07)*t+harmonic+.3)
            for frequency in (195.9977, 293.6648, 391.9954):
                left += .014*resolve*np.sin(2*np.pi*(frequency-.04)*t)
                right += .014*resolve*np.sin(2*np.pi*(frequency+.04)*t+.1)
            # Low, soft pulses enter gradually; no sharp trailer impacts.
            rhythm = np.clip((progress-.15)/.25, 0, 1)*(1-.65*np.clip((progress-.82)/.12, 0, 1))
            phase = np.mod(t, 2*beat)
            kick = .085*rhythm*np.exp(-phase*8)*np.sin(2*np.pi*(46*phase+3*(1-np.exp(-phase*15))))
            left += kick
            right += kick
            # Sparse bell-like upper notes, integrated rather than staccato.
            bell_phase = np.mod(t+beat, 8*beat)
            bell_frequency = np.where(np.floor(t/(8*beat)).astype(int)%2 == 0, 493.8833, 369.9944)
            bell = .025*(1-np.exp(-bell_phase*45))*np.exp(-bell_phase*1.6)*np.sin(2*np.pi*bell_frequency*t)
            left += bell
            right += .8*bell
            # Small transition swells follow actual edit boundaries.
            for boundary in boundaries:
                swell = np.exp(-((t-boundary)/.65)**2)
                left += .012*swell*np.sin(2*np.pi*(260*t+2*t*t))
                right += .012*swell*np.sin(2*np.pi*(263*t+2*t*t)+.2)
            noise = rng.normal(0, .0018, count)
            stereo = np.column_stack((left+noise, right-noise))
            stereo = .78*np.tanh(stereo*1.55)*envelope[:, None]
            maximum = max(maximum, float(np.max(np.abs(stereo))))
            square_sum += float(np.sum(stereo*stereo))
            sound.writeframes((stereo*32767).astype("<i2").tobytes())
    return {"sample_rate":SAMPLE_RATE, "channels":2, "sample_frames":total,
            "seconds":total/SAMPLE_RATE, "peak":maximum,
            "rms_dbfs":20*math.log10(max(1e-12, math.sqrt(square_sum/(2*total)))),
            "authorship":"Original procedural score generated by compose_film.py; no third-party samples"}


def compose(spec_path, destination):
    spec, shots = load_spec(spec_path)
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FileNotFoundError("FFmpeg and FFprobe must be installed and on PATH")
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    assets, clips, logs = (destination/name for name in ("titles", "clips", "logs"))
    for folder in (assets, clips, logs):
        folder.mkdir()
    copied_spec = destination/"edit.json"
    copied_spec.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(__file__, destination/"compose_film.py")
    total, boundaries, receipts = 0.0, [], []
    for index, shot in enumerate(shots):
        print(f"Encoding {index+1}/{len(shots)}: {shot.id} ({shot.seconds:.2f}s)", flush=True)
        title, persistent = assets/(shot.id+"-title.png"), assets/(shot.id+"-frame.png")
        title_panel(shot, title)
        persistent_panel(shot, persistent)
        first_path = shot.frames/f"frame-{shot.first:06d}.png"
        last_path = shot.frames/f"frame-{shot.first+shot.count-1:06d}.png"
        with Image.open(first_path) as source:
            dimensions = source.size
            source.verify()
        with Image.open(last_path) as source:
            if source.size != dimensions:
                raise ValueError("Frame dimensions changed inside " + shot.id)
            source.verify()
        fade = min(.35, shot.seconds/4)
        filters = (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,"
            "eq=contrast=1.035:brightness=-0.008:saturation=0.87,"
            "colorbalance=rs=-0.009:gs=0.005:bs=0.014:rh=0.012:gh=0.002:bh=-0.008,"
            "vignette=angle=0.22[graded];"
            + title_fade_filter(shot) +
            "[titled][2:v]overlay=0:0[framed];"
            f"[framed]fade=t=in:st=0:d={fade:.6f},"
            f"fade=t=out:st={shot.seconds-fade:.6f}:d={fade:.6f},format=yuv420p[v]"
        )
        clip = clips/(shot.id+".mp4")
        command = [ffmpeg, "-hide_banner", "-nostdin", "-n", "-threads", "2",
                   "-framerate", shot.fps, "-start_number", shot.first,
                   "-i", shot.frames/"frame-%06d.png", "-loop", "1", "-framerate", shot.fps, "-i", title,
                   "-loop", "1", "-framerate", shot.fps, "-i", persistent, "-filter_complex_threads", "1",
                   "-filter_complex", filters, "-map", "[v]", "-frames:v", shot.count,
                   "-r", shot.fps, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                   "-threads", "2", "-pix_fmt", "yuv420p", "-movflags", "+faststart", clip]
        run(command, logs/(shot.id+".log"))
        if total:
            boundaries.append(total)
        receipts.append({"id":shot.id, "source":str(shot.frames), "first_frame":shot.first,
                         "frame_count":shot.count, "fps":shot.fps, "seconds":shot.seconds,
                         "film_start_seconds":total, "first_frame_sha256":digest(first_path),
                         "last_frame_sha256":digest(last_path), "source_dimensions":dimensions,
                         "provenance":shot.provenance, "clip_sha256":digest(clip)})
        total += shot.seconds
    audio = synthesize_score(destination/"soundtrack.wav", total, boundaries)
    # Relative safe filenames keep concat independent of shell/path quoting.
    concat = destination/"concat.txt"
    concat.write_text("".join("file 'clips/"+shot.id+".mp4'\n" for shot in shots), encoding="utf-8")
    movie = destination/"film.mp4"
    command = [ffmpeg, "-hide_banner", "-nostdin", "-n", "-f", "concat", "-safe", "0", "-i", concat,
               "-i", destination/"soundtrack.wav", "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-ar", SAMPLE_RATE,
               "-af", "loudnorm=I=-18:LRA=9:TP=-1.5", "-t", f"{total:.9f}", "-movflags", "+faststart", movie]
    run(command, logs/"mux.log")
    probe = subprocess.run([ffprobe, "-v", "error", "-count_frames", "-show_streams", "-show_format",
                            "-of", "json", str(movie)], capture_output=True, text=True, check=True)
    metadata = json.loads(probe.stdout)
    (destination/"ffprobe.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
    sound = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
    expected_frames = sum(shot.count for shot in shots)
    if (video["codec_name"] != "h264" or video["pix_fmt"] != "yuv420p" or
        video["width"] != WIDTH or video["height"] != HEIGHT or sound["codec_name"] != "aac" or
        int(video["nb_read_frames"]) != expected_frames or
        abs(float(metadata["format"]["duration"])-total) > .15):
        raise RuntimeError("Final video metadata/frame count failed verification")
    run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", movie,
         "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], logs/"decode-check.log")
    manifest = {"format":"metarescue.film-edit.v1", "created_at":datetime.now(timezone.utc).isoformat(),
                "movie":str(movie), "sha256":digest(movie), "seconds":total,
                "width":WIDTH, "height":HEIGHT, "fps":shots[0].fps,
                "frame_count":expected_frames, "shots":receipts, "soundtrack":audio,
                "credit":spec.get("credit", ""), "full_av_decode_verified":True,
                "effects":"Editorial grade, letterboxing, typography, fades, original synthesized music. Native imagery otherwise preserved.",
                "licenses":"No third-party music or images added. Project-native asset provenance remains in the project asset catalog."}
    (destination/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"movie":str(movie), "seconds":total, "frame_count":expected_frames,
                      "verified":True}, ensure_ascii=False), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        _, shots = load_spec(args.spec)
        print(json.dumps({"shots":len(shots), "seconds":sum(shot.seconds for shot in shots)}, indent=2))
        return
    compose(args.spec, args.output)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
