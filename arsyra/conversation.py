"""Local, conservative invocation and short-lived Lara conversation context."""
from __future__ import annotations

import re
import random
import time
import unicodedata
import ast
import operator
from dataclasses import dataclass, field
from difflib import SequenceMatcher
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
    CALCULATION = "CALCULATION"
    ROAST = "ROAST"
    CORRECTION = "CORRECTION"
    CONFIRMATION = "CONFIRMATION"
    REJECTION = "REJECTION"
    GENERAL_CHAT = "GENERAL_CHAT"
    UNKNOWN = "UNKNOWN"


class ConversationState(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    WAITING_FOR_FOLLOWUP = "WAITING_FOR_FOLLOWUP"
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"


@dataclass
class ConversationMessage:
    role: str
    text: str
    intent: ConversationIntent | None
    timestamp: float
    language: str


@dataclass
class LaraTurn:
    expires_at: float
    bot_message_id: int | None = None
    turns: int = 0
    last_user_text: str = ""
    last_bot_text: str = ""
    last_reply_at: float = 0.0
    last_input_normalized: str = ""
    state: ConversationState = ConversationState.ACTIVE
    history: list[ConversationMessage] = field(default_factory=list)
    previous_intent: ConversationIntent | None = None
    previous_topic: str = ""
    pending_question: str | None = None


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
        if is_existing_feature_command(text) or is_existing_feature_command(strip_invocation(text)):
            return InvocationDecision(InvocationLevel.NO_INVOCATION, "protected_existing_feature")
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
        if (turn and turn.turns < self.max_followups
                and looks_like_follow_up(text, awaiting_clarification=bool(turn.pending_question))):
            return InvocationDecision(InvocationLevel.DIRECT_INVOCATION, "active_follow_up", True)
        # A mention buried in a statement or ambiguous short text never triggers a reply.
        if has_lara_name(text):
            return InvocationDecision(InvocationLevel.POSSIBLE_INVOCATION, "name_mentioned_in_statement")
        return InvocationDecision(InvocationLevel.NO_INVOCATION, "no_invocation")

    def record_reply(self, *, chat_id: int, user_id: int, user_text: str,
                     bot_message_id: int | None, bot_text: str,
                     continued: bool = False, intent: ConversationIntent | None = None,
                     now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        key = (int(chat_id), int(user_id))
        self.prune(now)
        if key not in self._turns and len(self._turns) >= self.max_contexts:
            oldest_key = min(self._turns, key=lambda item: self._turns[item].expires_at)
            self._turns.pop(oldest_key, None)
        previous = self._turns.get(key)
        turns = (previous.turns + 1) if (continued and previous) else 1
        correction = intent == ConversationIntent.CORRECTION
        topic = (extract_topic(user_text) if correction else
                 previous.previous_topic if continued and previous else extract_topic(user_text))
        pending = _response_has_pending_question(bot_text)
        history = list(previous.history) if continued and previous else []
        current_time = now
        history.extend([
            ConversationMessage("user", user_text[:500], intent, current_time, detect_language(user_text)),
            ConversationMessage("lara", bot_text[:1000], None, current_time, detect_language(bot_text)),
        ])
        if intent == ConversationIntent.CONFIRMATION:
            state = ConversationState.ACTIVE
            pending = None
        elif intent == ConversationIntent.REJECTION:
            state = ConversationState.ACTIVE
            pending = None
        elif correction or _response_requests_clarification(bot_text):
            state = ConversationState.WAITING_FOR_CLARIFICATION
        elif _response_requests_confirmation(bot_text):
            state = ConversationState.WAITING_FOR_CONFIRMATION
        elif pending:
            state = ConversationState.WAITING_FOR_FOLLOWUP
        else:
            state = ConversationState.ACTIVE
        self._turns[key] = LaraTurn(
            expires_at=now + self.ttl_seconds,
            bot_message_id=bot_message_id,
            turns=turns,
            last_user_text=user_text[:500],
            last_bot_text=bot_text[:1000],
            last_reply_at=now,
            last_input_normalized=normalize_invocation(user_text),
            state=state,
            history=history[-8:],
            previous_intent=intent,
            previous_topic=topic,
            pending_question=bot_text[:500] if pending else None,
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
        if classify_intent(text, continued=True) == ConversationIntent.CORRECTION:
            return text
        topic = turn.previous_topic
        return (text + " " + topic).strip() if topic else text

    def previous_user_text(self, chat_id: int, user_id: int) -> str:
        turn = self._turns.get((int(chat_id), int(user_id)))
        return turn.last_user_text if turn else ""

    def conversation_details(self, chat_id: int, user_id: int) -> dict[str, object]:
        turn = self._turns.get((int(chat_id), int(user_id)))
        if not turn:
            return {}
        return {
            "state": turn.state,
            "history": tuple(turn.history),
            "previous_intent": turn.previous_intent,
            "previous_topic": turn.previous_topic,
            "pending_question": turn.pending_question,
        }

    def prune(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        expired = [key for key, turn in self._turns.items() if turn.expires_at <= now]
        for key in expired:
            self._turns.pop(key, None)
        return len(expired)


_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_FILLER = {
    "طيب", "طب", "و", "او", "يعني", "كيف", "شو", "ما", "ماذا", "هل", "ممكن",
    "لارا", "lara", "بوت", "يا", "من", "انت", "انتي", "لو", "سمحتي", "بليز",
}
_FOLLOW_UP_RE = re.compile(
    r"^(?:وكمان|كمان|وفي شي تاني|وفي شيء تاني|في شي تاني|في شيء اخر|وهل|وكيف|واذا|وبعدين|"
    r"ما فهمت|مش فاهم|مو فاهم|ليش|لماذا|كيف|ممكن توضحي|ممكن تشرحي|"
    r"اشرح(?:ي)?لي|فهميني|وضح(?:ي)?لي|كمل(?:ي)?|تابعي|احكيلي اكتر|"
    r"شو قصدك|عنجد|متاكده|متاكد|طيب على|طيب بال|طيب بالم|طيب عن|اها|اه|اي|ايوه|نعم|صح|تمام|اوكي)",
    re.IGNORECASE,
)

_ARABIZI = {
    "ya": "يا", "keefek": "كيفك", "kifak": "كيفك", "kifik": "كيفك",
    "keefak": "كيفك", "kefak": "كيفك", "keef": "كيف", "kif": "كيف",
    "shou": "شو", "shu": "شو", "sho": "شو", "leh": "ليش", "leish": "ليش",
    "wen": "وين", "wein": "وين", "weinak": "وينك", "wenak": "وينك",
    "3adi": "عادي", "3adle": "عادي", "3lech": "ليش", "3ala": "على",
    "ma": "ما", "fhemet": "فهمت", "ma fhemet": "ما فهمت", "merci": "شكرا",
    "merciii": "شكرا", "thx": "شكرا", "lol": "هههه",
}


def normalize_invocation(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = _DIACRITICS.sub("", value)
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}))
    value = re.sub(r"\bl\s*a\s*r\s*a+\b", "lara", value, flags=re.IGNORECASE)
    value = re.sub(r"ل\s*ا\s*ر\s*ا+", "لارا", value)
    value = re.sub(r"([\w\u0600-\u06ff])\1{2,}", r"\1\1", value)
    value = re.sub(r"[^\w@\s]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    # Convert only common standalone Arabizi words; leave unknown Latin words untouched.
    tokens = value.split()
    normalized_tokens = []
    for token in tokens:
        normalized_tokens.append(_ARABIZI.get(token, token))
    value = " ".join(normalized_tokens)
    return re.sub(r"\s+", " ", value).strip()


def is_telegram_command(text: str) -> bool:
    return str(text or "").lstrip().startswith("/")


def has_lara_name(text: str) -> bool:
    return any(_is_name(word) for word in normalize_invocation(text).split())


def _is_name(word: str) -> bool:
    if re.fullmatch(r"(?:لارا+|lara+|بوت+|bot+)", word, re.IGNORECASE):
        return True
    if len(word) < 3 or len(word) > 5:
        return False
    return any(SequenceMatcher(None, word, target).ratio() >= 0.75
               for target in ("لارا", "lara", "بوت", "bot"))


def _is_reported_mention(word: str) -> bool:
    return word.startswith(("قال", "حكى", "حكت", "حكالي", "حكتلي", "تقول", "بتقول", "اسمه", "اسمها"))


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
    name_positions = [i for i, word in enumerate(words) if _is_name(word)]
    if not name_positions:
        return False
    for index in name_positions:
        before = words[:index]
        after = words[index + 1:]
        if not before:
            if after and (_is_reported_mention(after[0]) or after[0] in {"صديقتي", "صديقي", "صاحبي", "صاحبتي"}):
                return False
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


def looks_like_follow_up(text: str, *, awaiting_clarification: bool = False) -> bool:
    normalized = normalize_invocation(text)
    if not normalized or is_telegram_command(normalized):
        return False
    if is_correction(normalized):
        return True
    if normalized in {"طيب", "طب", "يعني", "بس", "اه", "اها", "تمام", "اوكي", "اي", "ايوه", "ايوا", "نعم", "لا", "عنجد", "صح", "كمل", "كملي", "وبعدين", "شو رايك", "شو رايك انت"}:
        return True
    if re.match(r"^(?:طيب|طب)\s*و?\s*(?:كيف|ليش|لماذا|ممكن|اشرح|فهميني|وضح|كملي|كمل|تابعي|شو يعني|على|بال|بالم|عن)", normalized):
        return True
    if re.match(r"^(?:و|يعني|بس)\s+(?:كيف|ليش|لماذا|هل|ممكن|شو يعني|اشرح|فهميني|وضح)", normalized):
        return True
    if _FOLLOW_UP_RE.search(normalized):
        return True
    if awaiting_clarification:
        tokens = normalized.split()
        # A short answer to Lara's outstanding question can continue without a name.
        has_question_form = bool(re.match(r"^(?:شو|كيف|ليش|وين|متى|هل|ماذا)\b", normalized))
        return 0 < len(tokens) <= 4 and not has_question_form
    return False


def is_correction(text: str) -> bool:
    t = normalize_invocation(text)
    return bool(re.search(r"^(?:لا|مو|مش)\s*(?:قصدي|قصدت|انا قصدي|يعني قصدي)|^قصدي\b|^لا قصدي شي تاني", t))


def _response_has_pending_question(text: str) -> bool:
    return "؟" in text or "?" in text or _response_requests_clarification(text)


def _response_requests_clarification(text: str) -> bool:
    normalized = normalize_invocation(text)
    return any(token in normalized for token in ("وضحلي", "حدديلي", "حددللي", "اي جزء", "اي نقطه", "احكيلي شو", "اكتب سؤالك", "قصدك الجديد"))


def _response_requests_confirmation(text: str) -> bool:
    normalized = normalize_invocation(text)
    return any(token in normalized for token in ("بدك اتابع", "هل تريد", "تريدين المتابعه", "موافق", "موافقه"))


def detect_language(text: str) -> str:
    has_arabic = bool(re.search(r"[\u0600-\u06ff]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "ar"
    if has_latin:
        return "latin_or_arabizi"
    return "unknown"


def extract_topic(text: str) -> str:
    normalized = normalize_invocation(strip_invocation(text))
    if re.search(r"(?:شي تاني|شي مختلف|موضوع تاني|موضوع مختلف)", normalized):
        return ""
    normalized = re.sub(r"^(?:لا|مو|مش)?\s*(?:قصدي|قصدت|يعني قصدي)\s*", "", normalized)
    tokens = [token for token in normalized.split()
              if token not in _FILLER and not _is_name(token)
              and token not in {"يعني", "بدي", "عايز", "اريد", "ممكن", "تساعديني", "ساعدني", "اشرح", "فهميني"}
              and len(token) > 1]
    return " ".join(tokens[-4:])[:140]


def strip_invocation(text: str) -> str:
    value = normalize_invocation(text)
    value = re.sub(r"@lara\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:يا\s+)?(?:لارا+|lara+|بوت+|bot+)\s*", "", value,
                   flags=re.IGNORECASE)
    value = re.sub(r"\s+(?:يا\s+)?(?:لارا+|lara+|بوت+|bot+)\s*$", "", value,
                   flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" \t\r\n؟?!.,،:؛")


def classify_intent(text: str, *, continued: bool = False,
                    previous_intent: ConversationIntent | None = None,
                    pending_question: str | None = None) -> ConversationIntent:
    t = normalize_invocation(text)
    has_question = "؟" in text or "?" in text
    if not t or re.fullmatch(r"(?:لارا+|lara+|بوت+|bot+)", t):
        return ConversationIntent.EMOTIONAL_RESPONSE
    if is_existing_feature_command(t):
        return ConversationIntent.COMMAND_TO_EXISTING_LARA_FEATURE
    if is_correction(t):
        return ConversationIntent.CORRECTION
    if t in {"لا", "لا شكرا", "مش هلأ", "مو هلق", "ما بدي", "مش موافق", "مو موافق"}:
        return ConversationIntent.REJECTION
    if t in {"اي", "ايوه", "ايوا", "نعم", "تمام", "اوكي", "صح", "اكيد", "موافق", "موافقه"}:
        return ConversationIntent.CONFIRMATION
    if re.search(r"(?:احسبي|احسب|كم يساوي|كم حاصل|calculate)", t) and re.search(
            r"\d+(?:\.\d+)?\s*[-+*/%]\s*-?\d", text):
        return ConversationIntent.CALCULATION
    if re.search(r"(?:قصف|اقصفي|حمصي|roast)", t):
        return ConversationIntent.ROAST
    if t in {"عنجد", "متاكده", "متاكد", "شو قصدك", "كيف يعني"}:
        return ConversationIntent.CLARIFICATION if not continued else ConversationIntent.FOLLOW_UP
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
    if re.search(r"(?:شكرا|مشكور|يسلمو|thanks|thank you)", t):
        return ConversationIntent.THANKS
    if re.search(r"(?:تصبح|تصبحي|باي|مع السلامه|الى اللقاء|bye|goodbye)", t):
        return ConversationIntent.GOODBYE
    if re.search(r"(?:نكت|اضحكيني|قوليلنا نكته|joke)", t):
        return ConversationIntent.JOKE
    if re.search(r"(?:شو رأيك|شو رايك|ما رأيك|ما رايك|برايك|تنصحيني|بتنصحي|recommend)", t):
        return ConversationIntent.OPINION_REQUEST
    if re.search(r"(?:فهميني|اشرح|اشرحي|فسري|فسريلي|ما معنى|شو يعني|ماذا يعني)", t):
        return ConversationIntent.EXPLANATION_REQUEST
    if re.search(r"(?:ساعديني|ساعدني|مساعده|مساعدة|عندي مشكله|عندي مشكلة|ممكن تساعد|بدي اسالك|بدي اسألك|عندي سؤال|اسمعي)", t):
        return ConversationIntent.HELP_REQUEST
    if re.search(r"(?:مرحبا|مرحب|اهلا|هلا|هلو|هاي|hello|hi)", t):
        return ConversationIntent.GREETING
    if re.search(r"كيفك|كيف حالك|شو اخبارك|شو عامله|شو عاملة|وينك|شو عم تعملي|how are you|how.s it going", t):
        return ConversationIntent.SMALL_TALK
    if re.search(r"(?:هههه|😂|🤣|😄|😅)", str(text or "")):
        return ConversationIntent.EMOTIONAL_RESPONSE
    if re.search(r"(?:اشتقتلك|وحشتيني|شو عم تعملي|شو عم تعمل|كيف يومك|شو عاملين)", t):
        return ConversationIntent.CASUAL_CHAT
    if has_question or re.search(r"\b(?:كيف|ليش|لماذا|متى|اين|وين|شو|ماذا|هل|ليه|where|why|how|what|when)\b", t):
        return ConversationIntent.QUESTION
    if re.search(r"(?:بدي|اريد|ممكن|ساعديني|ساعدني|اعمل|اعطيني|احكيلي|خبريني|tell me|please)", t):
        return ConversationIntent.REQUEST
    if re.search(r"(?:هههه|😂|🤣|😄|😅|عنجد|يا لطيف)", str(text or "")):
        return ConversationIntent.EMOTIONAL_RESPONSE
    if previous_intent is not None or pending_question:
        return ConversationIntent.GENERAL_CHAT
    if len(t.split()) <= 2:
        return ConversationIntent.UNKNOWN
    return ConversationIntent.GENERAL_CHAT


def is_existing_feature_command(text: str) -> bool:
    """Safety net for legacy text commands; main.py keeps their existing dispatch first."""
    t = normalize_invocation(text)
    protected = (
        "معلوماتي", "معلومات", "ايدي", "آيدي", "حسابي", "بينج", "ping", "سرعة البوت", "تست", "help", "الاوامر", "الأوامر",
        "رتبتي", "نقاطي", "تفاعلي", "اكس او", "إكس أو", "xo", "نزلي", "حملي", "بدي غنية",
        "اغنية", "تحميل", "لارا احكي", "احكي", "طرد", "طردي", "اطردي", "كتم", "اكتمي", "فك الكتم",
        "فكي الكتم", "الغاء كتم", "تحذير", "حذري", "تثبيت", "ثبتي", "قفل المحادثة", "اقفلي",
        "فتح المحادثة", "افتحي", "قفل الجروب", "فتح الجروب", "حظر", "احظر", "الغاء الحظر", "إلغاء الحظر", "فك الحظر", "مسح",
        "لارا طردي", "لارا اكتمي",
        "لارا حذري", "لارا اقفلي", "لارا فكي الكتم", "لارا ثبتي", "لارا افتحي",
        "رفع ادمن", "ارفع ادمن", "تنزيل ادمن", "نزل ادمن", "رفع مميز", "ارفع مميز",
        "تنزيل مميز", "نزل مميز", "ترقية مشرف", "تنزيل مشرف", "رفع مشرف", "عزل مشرف",
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
    if intent == ConversationIntent.CORRECTION:
        return "تمام، فهمت إنك تقصد شي مختلف. احكيلي شو قصدك الجديد وبمشي معك عليه."
    if intent == ConversationIntent.CONFIRMATION:
        return random.choice(["تمام 😊", "حلو، نكمل.", "تمام، معك."])
    if intent == ConversationIntent.REJECTION:
        return "ولا يهمك. إذا بتحب نغيّر الاتجاه، قلّي شو الأنسب إلك."
    if intent == ConversationIntent.FOLLOW_UP and topic:
        return f"بالنسبة لـ«{topic[:100]}»، {random.choice(['خليني أوضحها أكتر.', 'نكمل من هون.', 'شو الجزء اللي حابب تعرفه؟'])}"
    if intent == ConversationIntent.JOKE:
        return "بدك نكتة؟ اكتب «لارا نكتة» وبجيبلك وحدة من نكاتي 😄"
    if intent == ConversationIntent.EMOTIONAL_RESPONSE:
        return random.choice(["😄 أنا معك!", "😂 هون، سامعتك.", "😄 شو في؟"])
    if intent == ConversationIntent.GENERAL_CHAT:
        return "معك 😊 احكيلي أكتر عن اللي ببالك."
    if intent == ConversationIntent.UNKNOWN:
        return "أنا معك 😊 وضّحلي شو حابب تسأل أو تحكي."
    if intent == ConversationIntent.CALCULATION:
        return "اكتبلي العملية الحسابية بالأرقام والرموز، مثل 12 × 3."
    if intent == ConversationIntent.ROAST:
        return "إذا قصدك مزحة أو قصف خفيف، حدّدلي مين أو شو الموضوع 😄"
    if query:
        return f"ما لقيت جوابًا موثوقًا كفاية عن «{query[:120]}». فيك توضّحلي قصدك أو تعطيني تفاصيل أكثر؟"
    return "أنا هون معك 😊 شو حابب تسألني؟"


_CALC_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def calculate_local_request(text: str) -> float | int | None:
    """Evaluate a bounded arithmetic expression without eval or external services."""
    match = re.search(
        r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:\s*(?:\+|-|\*|/|//|%|\*\*)\s*[-+]?\d+(?:\.\d+)?)*(?![\w.])",
        text,
    )
    if not match:
        return None
    try:
        tree = ast.parse(match.group(0), mode="eval")

        def visit(node):
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if abs(node.value) > 1_000_000:
                    raise ValueError("number out of range")
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 8:
                    raise ValueError("exponent out of range")
                result = _CALC_OPS[type(node.op)](left, right)
                if abs(result) > 1_000_000_000:
                    raise ValueError("result out of range")
                return result
            if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
                return _CALC_OPS[type(node.op)](visit(node.operand))
            raise ValueError("unsupported expression")

        return visit(tree)
    except (SyntaxError, ArithmeticError, OverflowError, ValueError, ZeroDivisionError):
        return None


conversation_context = LaraConversationContext()
