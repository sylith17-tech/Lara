import asyncio
import os
import logging

logger = logging.getLogger(__name__)

async def run_ffmpeg_command(cmd: list):
    """تنفيذ أوامر FFmpeg بشكل غير متزامن وآمن تماماً (بدون Shell Injection)"""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_msg = stderr.decode()
        logger.error(f"[FFmpeg Error] {error_msg}")
        raise Exception(f"FFmpeg execution failed: {error_msg}")
    
    return True

async def trim_video(input_path: str, output_path: str, start_time: int, duration: int):
    """قص الفيديو من نقطة معينة ولمدة محددة"""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264", "-c:a", "aac",
        output_path
    ]
    logger.info(f"[Video Engine] Trimming video: {input_path} -> {output_path}")
    return await run_ffmpeg_command(cmd)

async def resize_aspect_ratio(input_path: str, output_path: str, ratio: str = "9:16"):
    """تغيير مقاس الفيديو ليناسب المنصات (مثل 9:16 لتيك توك أو ريلز)"""
    if ratio == "9:16":
        filter_complex = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    elif ratio == "1:1":
        filter_complex = "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2"
    else:
        filter_complex = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", filter_complex,
        "-c:v", "libx264", "-c:a", "aac",
        output_path
    ]
    logger.info(f"[Video Engine] Resizing video to {ratio}: {output_path}")
    return await run_ffmpeg_command(cmd)

async def mute_video(input_path: str, output_path: str):
    """إزالة الصوت تماماً من الفيديو"""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-an",
        "-c:v", "copy",
        output_path
    ]
    logger.info(f"[Video Engine] Muting video: {output_path}")
    return await run_ffmpeg_command(cmd)
