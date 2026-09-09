import os
import shutil
import uuid
import logging
import time

# إعداد نظام التسجيل الاحترافي
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_STORAGE = "storage"
JOBS_DIR = os.path.join(BASE_STORAGE, "jobs")

def create_job_storage():
    """ينشئ مجلداً فريداً وآمناً لكل عملية فيديو مع معالجة الأخطاء والتسجيل"""
    try:
        job_id = str(uuid.uuid4())[:8]
        job_path = os.path.join(JOBS_DIR, job_id)
        
        input_dir = os.path.join(job_path, "input")
        output_dir = os.path.join(job_path, "output")
        temp_dir = os.path.join(job_path, "temp")
        
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)
        
        logger.info(f"[STORAGE] Created secure job storage directory: {job_path}")
        return {
            "job_id": job_id,
            "job_path": job_path,
            "input": input_dir,
            "output": output_dir,
            "temp": temp_dir
        }
    except Exception as e:
        logger.error(f"[STORAGE] Failed to create job storage: {e}")
        raise

def cleanup_job_storage(job_path: str):
    """حذف مجلد الـ Job بالكامل بأمان تام لتحرير مساحة السيرفر"""
    if job_path and os.path.exists(job_path):
        try:
            shutil.rmtree(job_path)
            logger.info(f"[STORAGE] Successfully cleaned up and removed: {job_path}")
        except Exception as e:
            logger.error(f"[STORAGE] Error cleaning up directory {job_path}: {e}")

def cleanup_old_temp_files(max_age_hours=24):
    """تنظيف استباقي للعمليات المهملة التي تجاوزت المدة المحددة"""
    if not os.path.exists(JOBS_DIR):
        return
    current_time = time.time()
    for job_folder in os.listdir(JOBS_DIR):
        job_path = os.path.join(JOBS_DIR, job_folder)
        if os.path.isdir(job_path):
            folder_age = current_time - os.path.getmtime(job_path)
            if folder_age > (max_age_hours * 3600):
                cleanup_job_storage(job_path)
