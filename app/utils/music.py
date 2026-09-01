import os
import asyncio
import logging
import yt_dlp

logger = logging.getLogger(__name__)

async def search_and_download_song(query: str, download_dir: str = "downloads") -> tuple[str | None, str | None]:
    """البحث عن الأغنية وتحميلها بصيغة mp3"""
    os.makedirs(download_dir, exist_ok=True)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': f'{download_dir}/%(title)s.%(ext)s',
        'default_search': 'ytsearch1:',  # البحث عن النتيجة الأولى فقط
        'quiet': True,
        'no_warnings': True,
    }

    loop = asyncio.get_running_loop()
    
    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            if 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
            else:
                entry = info
            
            file_path = ydl.prepare_filename(entry)
            # استبدال الامتداد إلى mp3
            mp3_path = os.path.splitext(file_path)[0] + ".mp3"
            title = entry.get('title', 'أغنية بدون عنوان')
            return mp3_path, title

    try:
        mp3_path, title = await loop.run_in_executor(None, _download)
        if os.path.exists(mp3_path):
            return mp3_path, title
        return None, None
    except Exception as e:
        logger.error(f"Failed to download music: {e}")
        return None, None
