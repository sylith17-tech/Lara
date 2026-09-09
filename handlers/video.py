import os
import logging
from telegram import Update
from telegram.ext import ContextTypes
from services.pipeline import VideoPipelineOrchestrator
from services.storage import cleanup_job_storage

logger = logging.getLogger(__name__)

async def handle_incoming_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج قوي وآمن لاستلام الفيديوهات، ربطها بالـ Pipeline، ومعالجتها وإرسالها للمستخدم.
    """
    message = update.message
    
    # التحقق مما إذا كان المستخدم قد دخل جلسة التعديل عبر لوحة الـ VIP
    if not context.user_data.get('waiting_for_video', False):
        return  # تجاهل أي فيديو يُرسل خارج جلسة التعديل النشطة

    job_info = context.user_data.get('current_job')
    if not job_info:
        await message.reply_text("❌ حدث خطأ في جلسة العمل. يرجى إعادة بدء الجلسة من لوحة الـ VIP.")
        return

    # التحقق من وجود فيديو أو ملف فيديو في الرسالة
    video_file = message.video or message.document
    if not video_file:
        await message.reply_text("⚠️ يرجى إرسال ملف فيديو صحيح (صيغة MP4 أو ما شابه).")
        return

    # إرسال رسالة تفاعل أولية للمستخدم
    status_msg = await message.reply_text(
        "⏳ **تم استلام الفيديو بنجاح!**\n"
        "🤖 جاري تمرير الملف إلى محرك الـ AI والمعالجة عبر Pipeline...",
        parse_mode="Markdown"
    )

    input_file_path = None
    try:
        # تحميل ملف الفيديو من سيرفرات تيليجرام إلى مجلد الجلسة المؤقت (input)
        file_obj = await context.bot.get_file(video_file.file_id)
        input_file_path = os.path.join(job_info['input'], "source_video.mp4")
        await file_obj.download_to_drive(input_file_path)

        # استخراج وصف المستخدم (Prompt) من تعليق الفيديو أو استخدام وصف افتراضي
        user_prompt = message.caption if message.caption else "قم بتحويل وتعديل الفيديو بأفضل جودة سينمائية"
        logger.info(f"[Video Handler] Processing job {job_info['job_id']} with prompt: {user_prompt}")

        # تحديث حالة التقدم للمستخدم
        await status_msg.edit_text("⚙️ **جاري العمل...**\nالأذكياء الاصطناعيون ومحركات FFmpeg ينفذون العمليات الآن.")

        # تشغيل المشغل الهندسي المتكامل (Orchestrator Pipeline)
        pipeline = VideoPipelineOrchestrator(input_file_path, user_prompt)
        # تخصيص مسار الجلسة للمشغل ليستخدم نفس المجلد الفرعي
        pipeline.job_info = job_info 
        
        final_video_path = await pipeline.execute_pipeline()

        # إرسال الفيديو النهائي المعالج للمستخدم
        await status_msg.edit_text("📤 جاري رفع الفيديو المعالج...")
        
        with open(final_video_path, 'rb') as video_output:
            await message.reply_video(
                video=video_output,
                caption="✅ **تم إنجاز التعديل بنجاح بواسطة نظام VIP_ARM الذكي!** 🚀",
                parse_mode="Markdown"
            )

        await status_msg.delete()

    except Exception as e:
        logger.error(f"[Video Handler Error] Failed to process video: {e}")
        await status_msg.edit_text(f"❌ حدث خطأ أثناء معالجة الفيديو:\n`{str(e)}`", parse_mode="Markdown")

    finally:
        # التنظيف التلقائي الفوري لمجلد الجلسة بعد الانتهاء (سواء نجحت العملية أو فشلت)
        if job_info and 'job_path' in job_info:
            cleanup_job_storage(job_info['job_path'])
        
        # إعادة تعيين حالة المستخدم في الجلسة
        context.user_data['waiting_for_video'] = False
        context.user_data.pop('current_job', None)
