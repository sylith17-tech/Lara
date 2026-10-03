from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable


class MediaEngineError(RuntimeError):
    pass


def discover_binary(name: str) -> str:
    env_name = "FFMPEG_BINARY" if name == "ffmpeg" else "FFPROBE_BINARY"
    configured = os.getenv(env_name)
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which(name)
    if found:
        return found
    # static-ffmpeg is an optional dependency; use it only when installed.
    try:
        from static_ffmpeg import run  # type: ignore
        ffmpeg_path, ffprobe_path = run.get_or_fetch_platform_executables_else_raise()
        return ffmpeg_path if name == "ffmpeg" else ffprobe_path
    except Exception:
        pass
    raise MediaEngineError(f"{name} is unavailable; install it or set {env_name}.")


class MediaEngine:
    BRAND_NAME = "LARA"
    BRAND_SUBTITLE = "VIDEO STUDIO"
    INTRO_DURATION = 1.8
    INTRO_STYLE = "midnight-gradient"

    def __init__(self, timeout_seconds: int = 1800):
        self.ffmpeg = discover_binary("ffmpeg")
        self.ffprobe = discover_binary("ffprobe")
        self.timeout_seconds = max(10, int(timeout_seconds))

    async def _run(self, args: list[str], *, timeout: int | None = None,
                   progress: Callable[[str], None] | None = None) -> str:
        if progress:
            args = [args[0], "-progress", "pipe:1", "-nostats", *args[1:]]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stderr_task = asyncio.create_task(proc.stderr.read())
        try:
            chunks = []
            deadline = asyncio.get_running_loop().time() + (timeout or self.timeout_seconds)
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                if not line:
                    break
                chunks.append(line)
                if progress and line.startswith(b"out_time_ms="):
                    progress(line.decode("ascii", "ignore").strip().split("=", 1)[-1])
            await asyncio.wait_for(proc.wait(), timeout=max(0.1, deadline - asyncio.get_running_loop().time()))
            stdout = b"".join(chunks)
            stderr = await stderr_task
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
            raise
        if proc.returncode:
            detail = stderr.decode("utf-8", "replace")[-4000:]
            raise MediaEngineError(f"Media command failed ({proc.returncode}): {detail}")
        return stdout.decode("utf-8", "replace")

    async def probe_media(self, path: str | Path) -> dict[str, Any]:
        p = Path(path).resolve(strict=True)
        output = await self._run([
            self.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(p)
        ], timeout=60)
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise MediaEngineError("FFprobe returned invalid metadata") from exc
        if not data.get("streams"):
            raise MediaEngineError("Input contains no media streams")
        return data

    @staticmethod
    def _number(value: Any, low: float, high: float, label: str) -> float:
        try:
            n = float(value)
        except (TypeError, ValueError) as exc:
            raise MediaEngineError(f"Invalid {label}") from exc
        if not low <= n <= high:
            raise MediaEngineError(f"{label} must be between {low} and {high}")
        return n

    async def apply(self, source: str | Path, target: str | Path, op: dict[str, Any],
                    *, auxiliary: str | Path | None = None,
                    progress: Callable[[str], None] | None = None) -> Path:
        src, dst = Path(source).resolve(strict=True), Path(target).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        kind = op.get("type")
        common = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src)]
        if kind == "trim":
            start = self._number(op.get("start"), 0, 7200, "start")
            end = self._number(op.get("end"), start + 0.01, 7200, "end")
            args = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", str(start), "-i", str(src),
                    "-t", str(end - start), "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
        elif kind in ("trim_head", "trim_tail"):
            duration = self._number(op.get("duration"), 0.1, 7200, "trim duration")
            metadata = await self.probe_media(src)
            total = self._number(metadata.get("format", {}).get("duration"), duration + 0.01, 7200, "video duration")
            start = duration if kind == "trim_head" else 0.0
            end = total if kind == "trim_head" else total - duration
            if end <= start:
                raise MediaEngineError("Trim duration would remove the entire video")
            args = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", str(start), "-i", str(src),
                    "-t", str(end - start), "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
        elif kind == "trim_audio":
            start = self._number(op.get("start"), 0, 7200, "start")
            end = self._number(op.get("end"), start + 0.01, 7200, "end")
            args = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", str(start), "-i", str(src),
                    "-t", str(end - start), "-vn", "-c:a", "aac", str(dst)]
        elif kind == "remove_audio":
            args = common + ["-an", "-c:v", "libx264", "-preset", "veryfast", str(dst)]
        elif kind in ("resize", "compress"):
            if kind == "resize":
                width = int(self._number(op.get("width"), 64, 3840, "width"))
                height = int(self._number(op.get("height"), 64, 2160, "height"))
                vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
                args = common + ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
            else:
                crf = int(self._number(op.get("crf", 28), 18, 35, "crf"))
                args = common + ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-c:a", "aac", str(dst)]
        elif kind == "change_speed":
            factor = self._number(op.get("factor"), 0.25, 4, "speed")
            filters = []
            # atempo accepts [0.5, 2.0], so chain filters for the wider validated range.
            remaining = factor
            while remaining < 0.5:
                filters.append("atempo=0.5"); remaining /= 0.5
            while remaining > 2:
                filters.append("atempo=2.0"); remaining /= 2
            filters.append(f"atempo={remaining:.5f}")
            metadata = await self.probe_media(src)
            has_audio = any(s.get("codec_type") == "audio" for s in metadata.get("streams", []))
            has_video = any(s.get("codec_type") == "video" for s in metadata.get("streams", []))
            if has_video and has_audio:
                args = common + ["-filter_complex", f"[0:v]setpts=PTS/{factor}[v];[0:a]{','.join(filters)}[a]",
                                 "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", str(dst)]
            elif has_video:
                args = common + ["-vf", f"setpts=PTS/{factor}", "-an", "-c:v", "libx264", "-preset", "veryfast", str(dst)]
            else:
                args = common + ["-af", ",".join(filters), "-vn", "-c:a", "aac", str(dst)]
        elif kind in ("replace_audio", "mix_audio"):
            if auxiliary is None:
                raise MediaEngineError("The requested audio source is missing")
            aux = Path(auxiliary).resolve(strict=True)
            args = common + (["-stream_loop", "-1"] if op.get("repeat") else []) + ["-i", str(aux)]
            if kind == "replace_audio":
                try:
                    aux_meta = await self.probe_media(aux)
                except MediaEngineError:
                    raise
                if not any(s.get("codec_type") == "audio" for s in aux_meta.get("streams", [])):
                    raise MediaEngineError("The selected source has no audio stream")
                args += ["-filter_complex", "[1:a:0]apad[a]", "-map", "0:v:0?", "-map", "[a]",
                         "-c:v", "copy", "-c:a", "aac", "-shortest", str(dst)]
            else:
                volume = self._number(op.get("volume", 0.35), 0, 2, "music volume")
                auxiliary_meta = await self.probe_media(aux)
                if not any(s.get("codec_type") == "audio" for s in auxiliary_meta.get("streams", [])):
                    raise MediaEngineError("The selected source has no audio stream")
                metadata = await self.probe_media(src)
                has_audio = any(s.get("codec_type") == "audio" for s in metadata.get("streams", []))
                has_video = any(s.get("codec_type") == "video" for s in metadata.get("streams", []))
                if has_audio:
                    graph = f"[0:a]volume=1[a0];[1:a]volume={volume}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2"
                    if has_video:
                        graph += ",apad"
                    graph += "[a]"
                else:
                    graph = f"[1:a]volume={volume}" + (",apad" if has_video else "") + "[a]"
                args += ["-filter_complex", graph, "-map", "0:v:0?", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(dst)]
                if not has_video:
                    args.insert(-1, "-shortest")
        elif kind == "extract_audio":
            args = common + ["-vn", "-c:a", "aac", str(dst)]
        elif kind == "volume":
            volume = self._number(op.get("volume"), 0, 2, "volume")
            metadata = await self.probe_media(src)
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise MediaEngineError("Input has no audio stream to adjust")
            args = common + ["-af", f"volume={volume}", "-c:v", "copy", "-c:a", "aac", str(dst)]
        elif kind == "normalize_audio":
            metadata = await self.probe_media(src)
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise MediaEngineError("Input has no audio stream to normalize")
            args = common + ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy", "-c:a", "aac", str(dst)]
        elif kind == "audio_fade":
            duration = self._number(op.get("duration"), 0.1, 30, "audio fade duration")
            direction = op.get("direction", "in")
            if direction not in ("in", "out"):
                raise MediaEngineError("Invalid audio fade direction")
            metadata = await self.probe_media(src)
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise MediaEngineError("Input has no audio stream to fade")
            start = 0.0
            if direction == "out":
                total = self._number(metadata.get("format", {}).get("duration"), duration, 7200, "duration")
                start = max(0, total - duration)
            graph = f"[0:a]afade=t={direction}:st={start}:d={duration}[a]"
            args = common + ["-filter_complex", graph, "-map", "0:v:0?", "-map", "[a]",
                             "-c:v", "copy", "-c:a", "aac", str(dst)]
        elif kind == "audio_offset":
            offset = self._number(op.get("seconds"), -60, 60, "audio offset")
            metadata = await self.probe_media(src)
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise MediaEngineError("Input has no audio stream to synchronize")
            graph = f"[0:a]asetpts=PTS+({offset})/TB[a]"
            args = common + ["-filter_complex", graph, "-map", "0:v:0?", "-map", "[a]",
                             "-c:v", "copy", "-c:a", "aac", str(dst)]
        elif kind == "rotate":
            degrees = int(self._number(op.get("degrees"), 0, 270, "degrees"))
            filters = {90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}
            if degrees not in filters:
                raise MediaEngineError("Rotation must be 90, 180, or 270 degrees")
            args = common + ["-vf", filters[degrees], "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "flip":
            direction = op.get("direction")
            if direction not in ("horizontal", "vertical"):
                raise MediaEngineError("Invalid flip direction")
            vf = "hflip" if direction == "horizontal" else "vflip"
            args = common + ["-vf", vf, "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "fade":
            duration = self._number(op.get("duration"), 0.1, 30, "fade duration")
            typ = op.get("direction", "in")
            if typ not in ("in", "out"):
                raise MediaEngineError("Invalid fade direction")
            if typ == "in":
                vf = f"fade=t=in:st=0:d={duration}"
            else:
                metadata = await self.probe_media(src)
                total = self._number(metadata.get("format", {}).get("duration"), duration, 7200, "duration")
                vf = f"fade=t=out:st={max(0, total - duration)}:d={duration}"
            args = common + ["-vf", vf, "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "crop":
            width = int(self._number(op.get("width"), 64, 3840, "crop width"))
            height = int(self._number(op.get("height"), 64, 2160, "crop height"))
            args = common + ["-vf", f"crop={width}:{height}:(in_w-{width})/2:(in_h-{height})/2", "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "overlay_image":
            if auxiliary is None:
                raise MediaEngineError("The requested image is missing")
            duration = op.get("duration")
            position = op.get("position", "center")
            coords = {"center": ("(W-w)/2", "(H-h)/2"), "top_right": ("W-w-24", "24"),
                      "top_left": ("24", "24"), "bottom_right": ("W-w-24", "H-h-24"),
                      "bottom_left": ("24", "H-h-24")}.get(position)
            if not coords:
                raise MediaEngineError("Invalid image overlay position")
            base_meta = await self.probe_media(src)
            image_meta = await self.probe_media(auxiliary)
            base_video = next((s for s in base_meta["streams"] if s.get("codec_type") == "video"), {})
            overlay_video = next((s for s in image_meta["streams"] if s.get("codec_type") == "video"), {})
            max_width = max(32, int(int(base_video.get("width", 640)) * 0.35))
            overlay_width = min(max_width, int(overlay_video.get("width", max_width)))
            enable = "shortest=1" if duration is None else f"enable='between(t,0,{self._number(duration, 0.1, 7200, 'duration')})'"
            vf = f"[1:v]scale={overlay_width}:-1[overlay];[0:v][overlay]overlay={coords[0]}:{coords[1]}:{enable}"
            args = common + ["-loop", "1", "-i", str(Path(auxiliary).resolve(strict=True)), "-filter_complex", vf,
                             "-map", "0:a?", "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "text_overlay":
            text = str(op.get("text", ""))
            if not text or len(text) > 300:
                raise MediaEngineError("Overlay text must contain 1 to 300 characters")
            text_file = dst.parent / "overlay_text.txt"
            text_file.write_text(text, encoding="utf-8")
            escaped = text_file.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            fontsize = int(self._number(op.get("fontsize", 36), 18, 96, "text size"))
            position = op.get("position", "bottom")
            y = {"top": "h*0.08", "center": "(h-text_h)/2", "bottom": "h*0.82"}.get(position)
            if not y:
                raise MediaEngineError("Invalid text position")
            color = str(op.get("color", "white"))
            if not re.fullmatch(r"(?:white|black|yellow|red|blue|green|#[0-9a-fA-F]{6})", color):
                raise MediaEngineError("Unsupported text color")
            border = int(self._number(op.get("borderw", 2), 0, 6, "text border"))
            alpha = self._number(op.get("opacity", 1.0), 0.1, 1, "text opacity")
            start_at = self._number(op.get("start", 0), 0, 7200, "text start")
            end_at = op.get("end")
            enable = ""
            if end_at is not None:
                end_at = self._number(end_at, start_at + 0.1, 7200, "text end")
                enable = f":enable='between(t,{start_at},{end_at})'"
            box = ":box=1:boxcolor=black@0.55:boxborderw=14" if op.get("box") else ""
            args = common + ["-vf", f"drawtext=textfile='{escaped}':x=(w-text_w)/2:y={y}:fontsize={fontsize}:fontcolor={color}@{alpha}:borderw={border}:bordercolor=black:shadowx=2:shadowy=2{box}{enable}",
                             "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "burn_subtitles":
            if auxiliary is None:
                raise MediaEngineError("An SRT/VTT subtitle file is required")
            subtitle_path = Path(auxiliary).resolve(strict=True)
            if subtitle_path.suffix.lower() not in (".srt", ".vtt"):
                raise MediaEngineError("Only SRT and VTT subtitle files are accepted")
            escaped = subtitle_path.as_posix()
            for old, new in (("\\", "\\\\"), (":", "\\:"), ("'", "\\'"), (",", "\\,"), ("[", "\\["), ("]", "\\]")):
                escaped = escaped.replace(old, new)
            args = common + ["-vf", f"subtitles=filename='{escaped}'", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
        elif kind == "format_convert":
            fmt = str(op.get("format", "mp4")).lower()
            if fmt not in ("mp4", "mkv", "webm", "mov", "mp3", "wav", "aac"):
                raise MediaEngineError("Unsupported output format")
            encoders = {"mp3": ["-vn", "-c:a", "libmp3lame", "-q:a", "3"],
                        "wav": ["-vn", "-c:a", "pcm_s16le"], "aac": ["-vn", "-c:a", "aac"]}
            args = common + encoders.get(fmt, []) + [str(dst)]
        elif kind == "extract_frame":
            at = self._number(op.get("at", 0), 0, 7200, "frame time")
            args = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", str(at), "-i", str(src), "-frames:v", "1", str(dst)]
        elif kind == "grayscale":
            args = common + ["-vf", "hue=s=0", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
        elif kind == "hue":
            value = self._number(op.get("value"), -180, 180, "hue")
            args = common + ["-vf", f"hue=h={value}:s=1", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
        elif kind == "temperature":
            value = self._number(op.get("value"), -1, 1, "temperature")
            red, blue = max(-0.25, value * 0.25), max(-0.25, -value * 0.25)
            args = common + ["-vf", f"colorbalance=rs={red}:bs={blue}:rm={red / 2}:bm={blue / 2}", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
        elif kind in ("negative", "vignette", "film_grain"):
            vf = {"negative": "negate", "vignette": "vignette=PI/5",
                  "film_grain": "noise=alls=8:allf=t+u"}[kind]
            args = common + ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)]
        elif kind == "reverse":
            metadata = await self.probe_media(src)
            has_audio = any(s.get("codec_type") == "audio" for s in metadata.get("streams", []))
            args = common + (["-vf", "reverse", "-af", "areverse"] if has_audio else ["-vf", "reverse", "-an"])
            args += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)] if has_audio else ["-c:v", "libx264", "-preset", "veryfast", str(dst)]
        elif kind in ("brightness", "contrast", "saturation", "blur", "sharpen"):
            value = self._number(op.get("value"), -1, 1, kind)
            filters = {
                "brightness": f"eq=brightness={value}",
                "contrast": f"eq=contrast={max(0, 1 + value)}",
                "saturation": f"eq=saturation={max(0, 1 + value)}",
                "blur": f"boxblur={max(1, int(abs(value) * 10))}" if value else "null",
                "sharpen": f"unsharp=5:5:{max(0, value * 5)}:5:5:0" if value > 0 else "null",
            }
            args = common + ["-vf", filters[kind], "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "export":
            profile = str(op.get("profile", "balanced"))
            profiles = {
                "high": (20, "slow", "8M"),
                "balanced": (24, "veryfast", "4M"),
                "small": (30, "veryfast", "1800k"),
                "telegram": (28, "veryfast", "2200k"),
            }
            if profile not in profiles:
                raise MediaEngineError("Invalid export profile")
            crf, preset, bitrate = profiles[profile]
            args = common + ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-maxrate", bitrate,
                             "-bufsize", str(int(bitrate.rstrip("kM")) * (1000 if bitrate.endswith("k") else 1000000) * 2),
                             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)]
        elif kind == "concat_videos":
            raise MediaEngineError("Concatenation is handled by concat_videos()")
        else:
            raise MediaEngineError(f"Unsupported operation: {kind}")
        await self._run(args, progress=progress)
        await self.probe_media(dst)
        if not dst.is_file() or dst.stat().st_size == 0:
            raise MediaEngineError("FFmpeg did not produce a valid output")
        if progress:
            progress(f"Completed {kind}")
        return dst

    async def concat_videos(self, paths: list[str | Path], target: str | Path,
                            progress: Callable[[str], None] | None = None) -> Path:
        if len(paths) < 2:
            raise MediaEngineError("At least two video files are required")
        # Re-encode into a common H.264/AAC profile, then concatenate safely.
        dst = Path(target).resolve()
        normalized: list[Path] = []
        first_metadata = await self.probe_media(paths[0])
        first_video = next((stream for stream in first_metadata["streams"]
                            if stream.get("codec_type") == "video"), None)
        if not first_video:
            raise MediaEngineError("The first merge input has no video stream")
        portrait = int(first_video.get("height", 0)) > int(first_video.get("width", 0))
        canvas_width, canvas_height = (720, 1280) if portrait else (1280, 720)
        for i, path in enumerate(paths):
            p = Path(path).resolve(strict=True)
            intermediate = dst.parent / f"concat_part_{i}.mp4"
            metadata = await self.probe_media(p)
            has_audio = any(s.get("codec_type") == "audio" for s in metadata.get("streams", []))
            args = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(p)]
            if not has_audio:
                args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            await self._run(args + [
                             "-vf", f"scale={canvas_width}:{canvas_height}:force_original_aspect_ratio=decrease,pad={canvas_width}:{canvas_height}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                             "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0",
                             "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "48000", str(intermediate)], progress=progress)
            normalized.append(intermediate)
        listing = dst.parent / "concat_list.txt"
        def concat_quote(path: Path) -> str:
            return path.as_posix().replace("'", "'\\''")
        listing.write_text("".join(f"file '{concat_quote(p)}'\n" for p in normalized), encoding="utf-8")
        await self._run([self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0",
                         "-i", str(listing), "-c", "copy", str(dst)], progress=progress)
        await self.probe_media(dst)
        return dst

    async def create_preview(self, source: str | Path, target: str | Path, *, duration: float = 5.0) -> Path:
        src, dst = Path(source).resolve(strict=True), Path(target).resolve()
        length = self._number(duration, 1, 8, "preview duration")
        dst.parent.mkdir(parents=True, exist_ok=True)
        metadata = await self.probe_media(src)
        has_audio = any(s.get("codec_type") == "audio" for s in metadata.get("streams", []))
        args = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-t", str(length),
                "-vf", "scale=480:480:force_original_aspect_ratio=decrease,pad=480:480:(ow-iw)/2:(oh-ih)/2,fps=15,format=yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35"]
        if has_audio:
            args += ["-c:a", "aac", "-b:a", "48k"]
        else:
            args.append("-an")
        args.append(str(dst))
        await self._run(args)
        await self.probe_media(dst)
        return dst

    async def create_lara_intro(self, source: str | Path, target: str | Path) -> Path:
        """Create a short locally-rendered badge intro and prepend it to the edit."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:
            raise MediaEngineError("Pillow is required for the Lara intro") from exc
        src, dst = Path(source).resolve(strict=True), Path(target).resolve()
        metadata = await self.probe_media(src)
        stream = next((s for s in metadata["streams"] if s.get("codec_type") == "video"), None)
        if not stream:
            raise MediaEngineError("The Lara intro needs video input")
        width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
        portrait = height > width
        canvas_size = (720, 1280) if portrait else (1280, 720)
        w, h = canvas_size
        image_path = dst.parent / "lara_intro.png"
        image = Image.new("RGB", canvas_size)
        pixels = image.load()
        for y in range(h):
            blend = y / max(1, h - 1)
            color = (int(10 + 12 * blend), int(16 + 10 * blend), int(38 + 35 * blend))
            for x in range(w):
                pixels[x, y] = color
        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse((w * .12, h * .23, w * .88, h * .91), fill=(58, 84, 180, 35))
        badge_w, badge_h = int(w * .68), int(h * .25)
        x0, y0 = (w - badge_w) // 2, int(h * .36)
        draw.rounded_rectangle((x0, y0, x0 + badge_w, y0 + badge_h), radius=int(h * .055),
                               fill=(16, 26, 57, 235), outline=(123, 152, 255, 220), width=max(2, w // 320))
        draw.rounded_rectangle((x0 + w * .035, y0 + h * .035, x0 + w * .055, y0 + badge_h - h * .035),
                               radius=10, fill=(110, 226, 207, 255))
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(h * .105))
            subtitle_font = ImageFont.truetype("DejaVuSans.ttf", int(h * .033))
        except OSError:
            font, subtitle_font = ImageFont.load_default(), ImageFont.load_default()
        title_box = draw.textbbox((0, 0), self.BRAND_NAME, font=font)
        title_x = (w - (title_box[2] - title_box[0])) / 2
        draw.text((title_x, y0 + badge_h * .12), self.BRAND_NAME, font=font, fill=(255, 255, 255, 255))
        sub_box = draw.textbbox((0, 0), self.BRAND_SUBTITLE, font=subtitle_font)
        sub_x = (w - (sub_box[2] - sub_box[0])) / 2
        draw.text((sub_x, y0 + badge_h * .72), self.BRAND_SUBTITLE, font=subtitle_font, fill=(174, 196, 255, 255))
        image.save(image_path, format="PNG", optimize=True)
        intro = dst.parent / "lara_intro_clip.mp4"
        try:
            self._number(self.INTRO_DURATION, 0.8, 3, "intro duration")
            await self._run([self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loop", "1", "-i", str(image_path),
                             "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                             "-t", str(self.INTRO_DURATION), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
                             "-preset", "veryfast", "-crf", "27", "-c:a", "aac", "-shortest", str(intro)])
            await self.concat_videos([intro, src], dst)
        finally:
            image_path.unlink(missing_ok=True)
            intro.unlink(missing_ok=True)
            for intermediate in dst.parent.glob("concat_part_*.mp4"):
                intermediate.unlink(missing_ok=True)
            (dst.parent / "concat_list.txt").unlink(missing_ok=True)
        return dst
