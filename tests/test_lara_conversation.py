from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from arsyra.conversation import (
    ConversationIntent,
    InvocationLevel,
    LaraConversationContext,
    classify_intent,
    detect_invocation,
    is_telegram_command,
    is_existing_feature_command,
    looks_like_follow_up,
    normalize_invocation,
    strip_invocation,
)


@pytest.mark.parametrize("text", [
    "لارا كيفك", "يا لارا كيفك", "لارااا كيفك", "لَارا شو الأخبار",
    "Lara how are you", "LARA", "يا بوت", "بوت ساعدني", "هلو بوت",
    "@Lara شو رأيك؟", "شو رأيك يا لارا؟", "L a r a hello", "لاراااا 😂",
])
def test_direct_invocation_variants(text: str):
    assert detect_invocation(text)


@pytest.mark.parametrize("text", [
    "اسم صديقتي لارا", "لارا قالت إنها جاية", "وين الشباب؟",
    "ما بعرف", "يمكن باللعبة", "😂😂",
])
def test_non_invocation_and_subject_mentions_are_ignored(text: str):
    context = LaraConversationContext()
    decision = context.decide(chat_id=-100, user_id=1, text=text, now=100)
    assert decision.level != InvocationLevel.DIRECT_INVOCATION


def test_ambiguous_name_mention_has_low_confidence_and_no_reply():
    decision = LaraConversationContext().decide(chat_id=-100, user_id=1,
                                                text="لارا قالت إنها جاية", now=100)
    assert decision.level == InvocationLevel.POSSIBLE_INVOCATION


def test_invocation_normalizes_diacritics_repetition_and_punctuation():
    assert normalize_invocation("لَارااااا؟") == "لارا"
    assert detect_invocation("لَارااااا؟")
    assert strip_invocation("يا لارا، كيفك؟") == "كيفك"
    assert strip_invocation("شو رأيك يا لارا؟") == "شو رايك"


def test_context_is_per_user_and_group_and_expires():
    context = LaraConversationContext(ttl_seconds=60)
    start = context.decide(chat_id=-100, user_id=10, text="لارا شو يعني VPN؟", now=100)
    assert start.level == InvocationLevel.DIRECT_INVOCATION
    context.record_reply(chat_id=-100, user_id=10, user_text="لارا شو يعني VPN؟",
                         bot_message_id=500, bot_text="شرح VPN", now=100)

    followup = context.decide(chat_id=-100, user_id=10, text="طيب وكيف بستخدمه؟", now=110)
    assert followup.level == InvocationLevel.DIRECT_INVOCATION
    assert followup.continued
    assert "vpn" in context.contextual_query(chat_id=-100, user_id=10,
                                                text="طيب وكيف بستخدمه؟", continued=True).lower()

    other_user = context.decide(chat_id=-100, user_id=11, text="طيب وكيف بستخدمه؟", now=110)
    other_group = context.decide(chat_id=-200, user_id=10, text="طيب وكيف بستخدمه؟", now=110)
    expired = context.decide(chat_id=-100, user_id=10, text="طيب وكيف بستخدمه؟", now=161)
    assert other_user.level == InvocationLevel.NO_INVOCATION
    assert other_group.level == InvocationLevel.NO_INVOCATION
    assert expired.level == InvocationLevel.NO_INVOCATION


def test_context_does_not_follow_topic_change_or_unrelated_reply():
    context = LaraConversationContext()
    context.record_reply(chat_id=-100, user_id=10, user_text="لارا شو يعني VPN؟",
                         bot_message_id=500, bot_text="شرح VPN", now=100)
    changed_topic = context.decide(chat_id=-100, user_id=10,
                                   text="شو الأخبار بالشباب؟", now=105)
    reply_to_other = context.decide(chat_id=-100, user_id=10,
                                    text="طيب اشرحيلي", reply_to_other=True, now=105)
    assert changed_topic.level == InvocationLevel.NO_INVOCATION
    assert reply_to_other.level == InvocationLevel.NO_INVOCATION


def test_reply_to_lara_is_direct_but_reply_to_user_is_not():
    context = LaraConversationContext()
    assert context.reply_targets_lara(chat_id=-100, user_id=4, replied_message_id=50,
                                      replied_user_id=999, bot_user_id=999)
    assert not context.reply_targets_lara(chat_id=-100, user_id=4, replied_message_id=50,
                                          replied_user_id=8, bot_user_id=999)
    assert context.decide(chat_id=-100, user_id=4, text="طيب اشرحيلي",
                          reply_to_bot=True, now=100).level == InvocationLevel.DIRECT_INVOCATION


@pytest.mark.parametrize("command", ["/start", "/id", "/ping", "/calc 2+2", "/xo"])
def test_telegram_commands_never_become_lara_chat(command: str):
    assert is_telegram_command(command)
    assert LaraConversationContext().decide(chat_id=1, user_id=2, text=command).level == InvocationLevel.NO_INVOCATION


@pytest.mark.parametrize("text", [
    "يا لارا معلوماتي", "يا لارا ping", "يا لارا xo", "يا لارا طردي",
    "يا لارا فكي الكتم", "يا لارا قفل المحادثة", "يا لارا نزلي أغنية",
])
def test_legacy_feature_and_admin_phrases_are_never_reclassified(text: str):
    assert is_existing_feature_command(strip_invocation(text))


def test_duplicate_direct_invocation_has_short_cooldown_but_can_be_recalled():
    context = LaraConversationContext()
    context.record_reply(chat_id=1, user_id=2, user_text="لارا كيفك",
                         bot_message_id=4, bot_text="تمام", now=100)
    assert context.decide(chat_id=1, user_id=2, text="لارا كيفك", now=102).level == InvocationLevel.NO_INVOCATION
    assert context.decide(chat_id=1, user_id=2, text="لارا كيفك", now=105).level == InvocationLevel.DIRECT_INVOCATION


@pytest.mark.parametrize(("text", "expected"), [
    ("مرحبا", ConversationIntent.GREETING),
    ("ممكن تساعديني؟", ConversationIntent.HELP_REQUEST),
    ("فهميني شو يعني VPN", ConversationIntent.EXPLANATION_REQUEST),
    ("شو رأيك؟", ConversationIntent.OPINION_REQUEST),
    ("شكرا", ConversationIntent.THANKS),
    ("ما فهمت", ConversationIntent.CONFUSION),
    ("نكتة", ConversationIntent.JOKE),
    ("شو", ConversationIntent.CLARIFICATION),
])
def test_local_intent_classes(text: str, expected: ConversationIntent):
    assert classify_intent(text) == expected


def test_followup_matching_is_conservative():
    assert looks_like_follow_up("طيب وكيف بستخدمه؟")
    assert looks_like_follow_up("وفي شي تاني؟")
    assert not looks_like_follow_up("شو الأخبار بالشباب؟")
    assert not looks_like_follow_up("وين الشباب؟")


def test_admin_moderation_vip_commands_and_legacy_handlers_are_unchanged():
    root = Path(__file__).resolve().parents[1]
    current_main = (root / "main.py").read_text(encoding="utf-8")
    current_vip = (root / "main_vip.py").read_text(encoding="utf-8")
    baseline_main = subprocess.check_output(
        ["git", "show", "HEAD:main.py"], cwd=root, text=True
    )
    baseline_vip = subprocess.check_output(
        ["git", "show", "HEAD:main_vip.py"], cwd=root, text=True
    )

    def command_handlers(source: str) -> set[str]:
        return set(re.findall(r'CommandHandler\("([^"]+)"', source))

    assert command_handlers(current_main) == command_handlers(baseline_main)
    for callback in ('callback_data="vip_menu"', 'callback_data="start_video_edit"',
                     'callback_data="vip_stats"'):
        assert callback in current_vip and callback in baseline_vip
    for protected in ("handle_purge_commands", "handle_lock_toggle_commands", "check_media_locks",
                      "check_bad_words", "all_admin_triggers", "handle_msg"):
        assert protected in current_main and protected in baseline_main
    assert "CallbackQueryHandler(button_router)" in current_main
    assert "MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg)" in current_main


def test_group_dialogue_dispatch_remains_local_and_after_command_filters():
    root = Path(__file__).resolve().parents[1]
    source = (root / "main.py").read_text(encoding="utf-8")
    assert "from arsyra.engine import ask as arsyra_ask" in source
    assert "conversation_context.decide(" in source
    assert "MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg)" in source
    assert "openai_provider" not in source
