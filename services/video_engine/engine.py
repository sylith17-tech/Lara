from __future__ import annotations

import asyncio
import json
import os
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
            args = common + ["-i", str(aux)]
            if kind == "replace_audio":
                args += ["-filter_complex", "[1:a:0]apad[a]", "-map", "0:v:0?", "-map", "[a]",
                         "-c:v", "copy", "-c:a", "aac", "-shortest", str(dst)]
            else:
                volume = self._number(op.get("volume", 0.35), 0, 2, "music volume")
                metadata = await self.probe_media(src)
                has_audio = any(s.get("codec_type") == "audio" for s in metadata.get("streams", []))
                if has_audio:
                    graph = f"[0:a]volume=1[a0];[1:a]volume={volume}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]"
                else:
                    graph = f"[1:a]volume={volume}[a]"
                args += ["-filter_complex", graph, "-map", "0:v:0?", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(dst)]
        elif kind == "extract_audio":
            args = common + ["-vn", "-c:a", "aac", str(dst)]
        elif kind == "volume":
            volume = self._number(op.get("volume"), 0, 2, "volume")
            metadata = await self.probe_media(src)
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise MediaEngineError("Input has no audio stream to adjust")
            args = common + ["-af", f"volume={volume}", "-c:v", "copy", "-c:a", "aac", str(dst)]
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
            args = common + ["-vf", f"crop={width}:{height}", "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "overlay_image":
            if auxiliary is None:
                raise MediaEngineError("The requested image is missing")
            duration = op.get("duration")
            vf = "[0:v][1:v]overlay=(W-w)/2:(H-h)/2:shortest=1" if duration is None else \
                f"[0:v][1:v]overlay=(W-w)/2:(H-h)/2:enable='between(t,0,{self._number(duration, 0.1, 7200, 'duration')})'"
            args = common + ["-i", str(Path(auxiliary).resolve(strict=True)), "-filter_complex", vf,
                             "-map", "0:a?", "-c:v", "libx264", "-c:a", "aac", str(dst)]
        elif kind == "text_overlay":
            text = str(op.get("text", ""))
            if not text or len(text) > 300:
                raise MediaEngineError("Overlay text must contain 1 to 300 characters")
            text_file = dst.parent / "overlay_text.txt"
            text_file.write_text(text, encoding="utf-8")
            escaped = text_file.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            args = common + ["-vf", f"drawtext=textfile='{escaped}':x=(w-text_w)/2:y=h*0.82:fontsize=36:fontcolor=white:borderw=2:bordercolor=black",
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
        for i, path in enumerate(paths):
            p = Path(path).resolve(strict=True)
            intermediate = dst.parent / f"concat_part_{i}.mp4"
            await self._run([self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(p),
                             "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "48000", str(intermediate)], progress=progress)
            normalized.append(intermediate)
        listing = dst.parent / "concat_list.txt"
        def concat_quote(path: Path) -> str:
            return path.as_posix().replace("'", "'\\''")
        listing.write_text("".join(f"file '{concat_quote(p)}'\n" for p in normalized), encoding="utf-8")
        await self._run([self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0",
                         "-i", str(listing), "-c", "copy", str(dst)], progress=progress)
        await self.probe_media(dst)
        return dst
