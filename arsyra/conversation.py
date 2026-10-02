"""Local, conservative invocation and short-lived Lara conversation context."""
from __future__ import annotations

import re
import random
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class InvocationLevel(str, Enum):
    DIRECT_INVOCATION = "DIRECT_INVOCATION"
    POSSIBLE_INVOCATION = "POSSIBLE_INVOCATION"
    NO_INVOCATION = "NO_INVOCATION"


class ConversationIntent(str, Enum):
    GREETING = "GREETING"
    SMALL_TALK = "SMALL_TALK"
    QUESTION = "QUESTION"
    REQUEST = "REQUEST"
    EXPLANATION_REQUEST = "EXPLANATION_REQUEST"
    OPINION_REQUEST = "OPINION_REQUEST"
    HELP_REQUEST = "HELP_REQUEST"
    FOLLOW_UP = "FOLLOW_UP"
    JOKE = "JOKE"
    CASUAL_CHAT = "CASUAL_CHAT"
    THANKS = "THANKS"
    GOODBYE = "GOODBYE"
    CONFUSION = "CONFUSION"
    CLARIFICATION = "CLARIFICATION"
    EMOTIONAL_RESPONSE = "EMOTIONAL/CASUAL_RESPONSE"
    COMMAND_TO_EXISTING_LARA_FEATURE = "COMMAND_TO_EXISTING_LARA_FEATURE"


@dataclass
class LaraTurn:
    expires_at: float
    bot_message_id: int | None = None
    turns: int = 0
    last_user_text: str = ""
    last_bot_text: str = ""
    last_reply_at: float = 0.0
    last_input_normalized: str = ""


@dataclass(frozen=True)
class InvocationDecision:
    level: InvocationLevel
    reason: str
    continued: bool = False


@dataclass
class LaraConversationContext:
    ttl_seconds: int = 120
    max_followups: int = 4
    duplicate_window_seconds: int = 4
    max_contexts: int = 10000
    _turns: dict[tuple[int, int], LaraTurn] = field(default_factory=dict)

    def decide(self, *, chat_id: int, user_id: int, text: str,
               reply_to_bot: bool = False, reply_to_other: bool = False,
               now: float | None = None) -> InvocationDecision:
        now = time.monotonic() if now is None else now
        key = (int(chat_id), int(user_id))
        turn = self._turns.get(key)
        if turn and turn.expires_at <= now:
            self._turns.pop(key, None)
            turn = None
        if is_telegram_command(text):
            return InvocationDecision(InvocationLevel.NO_INVOCATION, "telegram_command")
        direct = detect_invocation(text)
        normalized = normalize_invocation(text)
        if direct:
            if (turn and turn.last_input_normalized == normalized
                    and now - turn.last_reply_at < self.duplicate_window_seconds):
                return InvocationDecision(InvocationLevel.NO_INVOCATION, "duplicate_cooldown")
            return InvocationDecision(InvocationLevel.DIRECT_INVOCATION, "explicit_name")
        if reply_to_bot:
            return InvocationDecision(InvocationLevel.DIRECT_INVOCATION, "reply_to_lara", bool(turn))
        if reply_to_other:
            return InvocationDecision(InvocationLevel.NO_INVOCATION, "reply_to_other_user")
        if turn and turn.turns < self.max_followups and looks_like_follow_up(text):
            return InvocationDecision(InvocationLevel.DIRECT_INVOCATION, "active_follow_up", True)
        # A mention buried in a statement or ambiguous short text never triggers a reply.
        if has_lara_name(text):
            return InvocationDecision(InvocationLevel.POSSIBLE_INVOCATION, "name_mentioned_in_statement")
        return InvocationDecision(InvocationLevel.NO_INVOCATION, "no_invocation")

    def record_reply(self, *, chat_id: int, user_id: int, user_text: str,
                     bot_message_id: int | None, bot_text: str,
                     continued: bool = False, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        key = (int(chat_id), int(user_id))
        self.prune(now)
        if key not in self._turns and len(self._turns) >= self.max_contexts:
            oldest_key = min(self._turns, key=lambda item: self._turns[item].expires_at)
            self._turns.pop(oldest_key, None)
        previous = self._turns.get(key)
        turns = (previous.turns + 1) if (continued and previous) else 1
        self._turns[key] = LaraTurn(
            expires_at=now + self.ttl_seconds,
            bot_message_id=bot_message_id,
            turns=turns,
            last_user_text=user_text[:500],
            last_bot_text=bot_text[:1000],
            last_reply_at=now,
            last_input_normalized=normalize_invocation(user_text),
        )

    def reply_targets_lara(self, *, chat_id: int, user_id: int,
                           replied_message_id: int | None, replied_user_id: int | None,
                           bot_user_id: int | None) -> bool:
        if replied_message_id is None:
            return False
        if bot_user_id is not None and replied_user_id == bot_user_id:
            return True
        turn = self._turns.get((int(chat_id), int(user_id)))
        return bool(turn and turn.bot_message_id == replied_message_id)

    def contextual_query(self, *, chat_id: int, user_id: int, text: str,
                         continued: bool) -> str:
        if not continued:
            return text
        turn = self._turns.get((int(chat_id), int(user_id)))
        if not turn:
            return text
        # Carry a few topic words into terse follow-ups ("طيب وكيف أستخدمه؟").
        topic = [w for w in normalize_invocation(turn.last_user_text).split()
                 if w not in _FILLER and not _is_name(w) and len(w) > 1]
        return (text + " " + " ".join(topic[-3:])).strip() if topic else text

    def previous_user_text(self, chat_id: int, user_id: int) -> str:
        turn = self._turns.get((int(chat_id), int(user_id)))
        return turn.last_user_text if turn else ""

    def prune(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        expired = [key for key, turn in self._turns.items() if turn.expires_at <= now]
        for key in expired:
            self._turns.pop(key, None)
        return len(expired)


_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_NAME_RE = re.compile(r"(?:لارا+|lara+|بوت+|bot+)", re.IGNORECASE)
_FILLER = {
    "طيب", "طب", "و", "او", "يعني", "كيف", "شو", "ما", "ماذا", "هل", "ممكن",
    "لارا", "lara", "بوت", "يا", "من", "انت", "انتي", "لو", "سمحتي", "بليز",
}
_FOLLOW_UP_RE = re.compile(
    r"^(?:وكمان|وفي شي تاني|وفي شيء تاني|في شي تاني|في شيء اخر|وهل|وكيف|واذا|وبعدين|"
    r"ما فهمت|مش فاهم|مو فاهم|ليش|لماذا|كيف|ممكن توضحي|ممكن تشرحي|"
    r"اشرح(?:ي)?لي|فهميني|وضح(?:ي)?لي|كملي|تابعي|احكيلي اكتر|اها|اه|تمام|اوكي)",
    re.IGNORECASE,
)


def normalize_invocation(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = _DIACRITICS.sub("", value)
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    value = re.sub(r"\bl\s*a\s*r\s*a+\b", "lara", value, flags=re.IGNORECASE)
    value = re.sub(r"ل\s*ا\s*ر\s*ا+", "لارا", value)
    value = re.sub(r"([\w\u0600-\u06ff])\1{2,}", r"\1\1", value)
    value = re.sub(r"[^\w@\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def is_telegram_command(text: str) -> bool:
    return str(text or "").lstrip().startswith("/")


def has_lara_name(text: str) -> bool:
    return bool(_NAME_RE.search(normalize_invocation(text)))


def _is_name(word: str) -> bool:
    return bool(re.fullmatch(r"(?:لارا+|lara+|بوت+|bot+)", word, re.IGNORECASE))


def detect_invocation(text: str) -> bool:
    """Detect clear vocative/name calls; reject mentions used as sentence subjects."""
    raw = normalize_invocation(text)
    if not raw or is_telegram_command(raw):
        return False
    if re.search(r"@lara\b", raw, re.IGNORECASE):
        return True
    words = raw.split()
    if not words:
        return False
    name_positions = [i for i, word in enumerate(words)
                      if re.fullmatch(r"(?:لارا+|lara+|بوت+|bot+)", word, re.IGNORECASE)]
    if not name_positions:
        return False
    for index in name_positions:
        before = words[:index]
        after = words[index + 1:]
        if not before:
            if not after or after[0] in {"قال", "قالت", "حكت", "اسم", "صديقتي", "صديقي", "اسمها", "اسمه"}:
                    return not after and words[index].startswith(("لارا", "lara"))
            return True
        if before[-1] == "يا":
            return True
        if index == len(words) - 1 and len(before) <= 5:
            # A trailing vocative such as "شو رأيك يا لارا".
            if before[-1] in {"يا", "lara", "لارا"} or any(
                w in {"رأيك", "رايك", "تقولين", "بتقولي", "هلو", "هلا", "مرحبا", "اهلا", "هاي", "hello", "hi"}
                for w in before
            ):
                return True
    return False


def looks_like_follow_up(text: str) -> bool:
    normalized = normalize_invocation(text)
    if not normalized or is_telegram_command(normalized):
        return False
    if normalized in {"طيب", "طب", "يعني", "بس", "اه", "اها", "تمام", "اوكي"}:
        return True
    if re.match(r"^(?:طيب|طب)\s*و?\s*(?:كيف|ليش|لماذا|ممكن|اشرح|فهميني|وضح|كملي|تابعي|شو يعني)", normalized):
        return True
    if re.match(r"^(?:و|يعني|بس)\s+(?:كيف|ليش|لماذا|هل|ممكن|شو يعني|اشرح|فهميني)", normalized):
        return True
    return bool(_FOLLOW_UP_RE.search(normalized))


def strip_invocation(text: str) -> str:
    value = normalize_invocation(text)
    value = re.sub(r"@lara\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:يا\s+)?(?:لارا+|lara+|بوت+|bot+)\s*", "", value,
                   flags=re.IGNORECASE)
    value = re.sub(r"\s+(?:يا\s+)?(?:لارا+|lara+|بوت+|bot+)\s*$", "", value,
                   flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" \t\r\n؟?!.,،:؛")


def classify_intent(text: str, *, continued: bool = False) -> ConversationIntent:
    t = normalize_invocation(text)
    if not t or re.fullmatch(r"(?:لارا+|lara+|بوت+|bot+)", t):
        return ConversationIntent.EMOTIONAL_RESPONSE
    if is_existing_feature_command(t):
        return ConversationIntent.COMMAND_TO_EXISTING_LARA_FEATURE
    if re.search(r"(?:قصدك|تقصد|تقصدين|يعني انتِ|يعني انت)", t):
        return ConversationIntent.CLARIFICATION
    if re.search(r"ما فهمت|مش فاهم|مو فاهم|مش فاهمه|مو فاهمه", t):
        return ConversationIntent.CONFUSION
    if continued and looks_like_follow_up(t):
        if re.search(r"ما فهمت|مش فاهم|مو فاهم|وضح|اشرح", t):
            return ConversationIntent.CONFUSION
        if re.search(r"ليش|لماذا|كيف|طيب|طب|وبعدين|في شي تاني|في شيء اخر", t):
            return ConversationIntent.FOLLOW_UP
        return ConversationIntent.CLARIFICATION
    if t in {"ليش", "لماذا", "كيف", "شو", "ماذا", "ايش", "طيب شو", "طيب كيف"}:
        return ConversationIntent.CLARIFICATION
    if re.search(r"\b(?:شكرا|مشكور|يسلمو|thanks|thank you)\b", t):
        return ConversationIntent.THANKS
    if re.search(r"(?:تصبح|تصبحي|باي|مع السلامه|الى اللقاء|bye|goodbye)", t):
        return ConversationIntent.GOODBYE
    if re.search(r"(?:نكت|اضحكيني|قوليلنا نكته)", t):
        return ConversationIntent.JOKE
    if re.search(r"(?:شو رأيك|شو رايك|ما رأيك|ما رايك|برايك|تنصحيني|بتنصحي|recommend)", t):
        return ConversationIntent.OPINION_REQUEST
    if re.search(r"(?:فهميني|اشرح|اشرحي|فسري|فسريلي|ما معنى|شو يعني|ماذا يعني)", t):
        return ConversationIntent.EXPLANATION_REQUEST
    if re.search(r"(?:ساعديني|ساعدني|مساعده|مساعدة|عندي مشكله|عندي مشكلة|ممكن تساعد|بدي اسالك|بدي اسألك|عندي سؤال|اسمعي)", t):
        return ConversationIntent.HELP_REQUEST
    if re.search(r"(?:مرحبا|مرحب|اهلا|هلا|هلو|هاي|hello|hi)\b", t):
        return ConversationIntent.GREETING
    if re.search(r"كيفك|كيف حالك|شو اخبارك|شو عامله|شو عاملة|وينك|شو عم تعملي|how are you|how.s it going", t):
        return ConversationIntent.SMALL_TALK
    if re.search(r"(?:هههه|😂|🤣|😄|😅)", str(text or "")):
        return ConversationIntent.EMOTIONAL_RESPONSE
    if re.search(r"(?:اشتقتلك|وحشتيني|شو عم تعملي|شو عم تعمل|كيف يومك|شو عاملين)", t):
        return ConversationIntent.CASUAL_CHAT
    if re.search(r"\?|؟|\b(?:كيف|ليش|لماذا|متى|اين|وين|شو|ماذا|هل)\b", t):
        return ConversationIntent.QUESTION
    return ConversationIntent.REQUEST


def is_existing_feature_command(text: str) -> bool:
    """Safety net for legacy text commands; main.py keeps their existing dispatch first."""
    t = normalize_invocation(text)
    protected = (
        "معلوماتي", "معلومات", "ايدي", "آيدي", "حسابي", "بينج", "ping", "سرعة البوت", "تست", "help", "الاوامر", "الأوامر",
        "رتبتي", "نقاطي", "تفاعلي", "اكس او", "إكس أو", "xo", "نزلي", "حملي", "بدي غنية",
        "اغنية", "تحميل", "لارا احكي", "احكي", "طرد", "طردي", "اطردي", "كتم", "اكتمي", "فك الكتم",
        "فكي الكتم", "الغاء كتم", "تحذير", "حذري", "تثبيت", "ثبتي", "قفل المحادثة", "اقفلي",
        "فتح المحادثة", "افتحي", "قفل الجروب", "فتح الجروب", "لارا طردي", "لارا اكتمي",
        "لارا حذري", "لارا اقفلي", "لارا فكي الكتم", "لارا ثبتي", "لارا افتحي",
    )
    return any(t == normalize_invocation(item) or t.startswith(normalize_invocation(item) + " ")
               for item in protected)


def natural_fallback(query: str, intent: ConversationIntent, *, topic: str = "") -> str:
    """Short, local fallback for intents that the legacy dialogue corpus misses."""
    if intent == ConversationIntent.GREETING:
        return random.choice(["أهلًا وسهلًا! شو حابب نحكي؟ 🌷", "يا أهلا فيك 😄 شو الأخبار؟"])
    if intent == ConversationIntent.SMALL_TALK:
        return random.choice(["أنا بخير وجاهزة أحكي معك 😄 وإنت كيفك؟", "تمام الحمدلله، حلو إنك سألت 🌷"])
    if intent == ConversationIntent.THANKS:
        return random.choice(["العفو، أنا موجودة إذا احتجت أي شي 🌷", "ولو! بالخدمة دايمًا 😄"])
    if intent == ConversationIntent.GOODBYE:
        return random.choice(["مع السلامة، دير بالك على حالك 🌙", "تصبح على خير، منشوفك على خير 🌙"])
    if intent == ConversationIntent.HELP_REQUEST:
        return "أكيد، احكيلي شو المشكلة أو الشي اللي بدك مساعدة فيه وبمشي معك خطوة خطوة."
    if intent == ConversationIntent.EXPLANATION_REQUEST:
        return "أكيد، حدّدلي المصطلح أو الفكرة اللي بدك شرحها، وبشرحها ببساطة."
    if intent == ConversationIntent.OPINION_REQUEST:
        return "أكيد، احكيلي عن الموضوع أو الخيارين اللي بدك رأيي فيهم."
    if intent == ConversationIntent.CONFUSION:
        return "ولا يهمك. أي جزء حسّيته مو واضح؟ بشرحه بطريقة أبسط."
    if intent == ConversationIntent.CLARIFICATION:
        return "أي نقطة تقصد؟ ذكّريني بالموضوع أو اكتبي سؤالك كامل وأنا أوضحه."
    if intent == ConversationIntent.FOLLOW_UP and topic:
        return f"بالنسبة لـ«{topic[:100]}»، أي جزء بتحب نكمل فيه؟"
    if intent == ConversationIntent.JOKE:
        return "بدك نكتة؟ اكتب «لارا نكتة» وبجيبلك وحدة من نكاتي 😄"
    if intent == ConversationIntent.EMOTIONAL_RESPONSE:
        return "😄 أنا معك!"
    if query:
        return f"ما لقيت جوابًا موثوقًا كفاية عن «{query[:120]}». فيك توضّحلي قصدك أو تعطيني تفاصيل أكثر؟"
    return "أنا هون معك 😊 شو حابب تسألني؟"


conversation_context = LaraConversationContext()
