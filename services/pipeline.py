import os
import logging
import asyncio
from typing import Dict, Any, List
from services.storage import create_job_storage, cleanup_job_storage
from services.planner import validate_and_filter_plan
from services.video import trim_video, resize_aspect_ratio, mute_video
from services.ai import ai_manager

logger = logging.getLogger(__name__)

class VideoPipelineOrchestrator:
    def __init__(self, input_file_path: str, user_prompt: str):
        self.input_file = input_file_path
        self.prompt = user_prompt
        self.job_info = create_job_storage()
        self.current_working_file = self.input_file

    async def generate_ai_plan(self) -> List[Dict[str, Any]]:
        """
        محاكاة/استدعاء الـ AI Planner لتحويل وصف المستخدم إلى JSON آمن ومفلتر.
        في النسخة الحالية، يتم بناء الخطة بناءً على التحليل الذكي للنص.
        """
        logger.info(f"[Pipeline] Analyzing user prompt: '{self.prompt}'")
        
        # مثال افتراضي لهيكل JSON يمثّله الـ AI Planner بناءً على طلب المستخدم
        # (لاحقاً سيتم ربطه مباشرة بـ OpenAI API أو نموذج LLM محلي عبر JSON Mode)
        simulated_ai_json = '{"operations": [{"type": "trim", "start": 0, "duration": 10}, {"type": "aspect_ratio", "value": "9:16"}]}'
        
        validated_ops = validate_and_filter_plan(simulated_ai_json)
        return validated_ops

    async def execute_pipeline(self) -> str:
        """
        تنفيذ خطة العمليات بشكل متسلسل وآمن، مع نقل الملفات المؤقتة بين المراحل.
        """
        try:
            operations = await self.generate_ai_plan()
            if not operations:
                raise Exception("No valid operations found or plan rejected by security whitelist.")

            step_counter = 0
            for op in operations:
                step_counter += 1
                op_type = op.get("type")
                engine = op.get("engine")
                
                output_filename = f"step_{step_counter}_{op_type}.mp4"
                output_path = os.path.join(self.job_info['temp'], output_filename)

                logger.info(f"[Pipeline] Executing Operation: {op_type} via Engine: {engine}")

                # التوجيه الذكي للعمليات بناءً على الـ Whitelist والـ Router
                if engine == "ffmpeg":
                    if op_type == "trim":
                        start = op.get("start", 0)
                        duration = op.get("duration", 10)
                        await trim_video(self.current_working_file, output_path, start, duration)
                    elif op_type == "aspect_ratio":
                        ratio = op.get("value", "9:16")
                        await resize_aspect_ratio(self.current_working_file, output_path, ratio)
                    elif op_type == "mute":
                        await mute_video(self.current_working_file, output_path)
                
                elif engine == "model_a":
                    await ai_manager.process_model_a(self.current_working_file, self.prompt, output_path)
                
                elif engine == "model_b":
                    await ai_manager.process_model_b(self.current_working_file, self.prompt, output_path)

                # تحديث ملف العمل الحالي للمرحلة التالية
                self.current_working_file = output_path

            # نقل الملف النهائي إلى مجلد الـ Output الخاص بالجلسة
            final_output_path = os.path.join(self.job_info['output'], "final_result.mp4")
            if os.path.exists(self.current_working_file):
                os.rename(self.current_working_file, final_output_path)
            
            logger.info(f"[Pipeline] Job {self.job_info['job_id']} completed successfully.")
            return final_output_path

        except Exception as e:
            logger.error(f"[Pipeline Error] Failed execution for job {self.job_info['job_id']}: {e}")
            cleanup_job_storage(self.job_info['job_path'])
            raise e
