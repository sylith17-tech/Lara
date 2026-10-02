from __future__ import annotations

import csv
import json
import random
import re
import unicodedata
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "arabic_dialogues.csv"
INDEX_DIR = BASE_DIR / "index"
INDEX_FILE = INDEX_DIR / "pairs.json"

DEFAULT_THRESHOLD = 68

ARABIC_DIACRITICS = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)

SPEAKER_LINE = re.compile(
    r"^\s*(?:\*\*)?\s*([^:\n]{1,80}?)(?:\*\*)?\s*:\s*(.+?)\s*$"
)

MULTI_SPACE = re.compile(r"\s+")

# كلمات شائعة جدًا ولا تساعد في تحديد موضوع السؤال.
STOP_WORDS = {
    "ما", "ماذا", "متى", "اين", "أين", "كيف", "هل", "لماذا", "ليش",
    "شو", "ايش", "أي", "اي", "من", "كم", "هو", "هي", "هم", "انا",
    "أنا", "انت", "أنت", "انتي", "أنتي", "هذا", "هذه", "ذلك", "تلك",
    "هناك", "هنا", "عن", "على", "في", "من", "الى", "إلى", "مع",
    "و", "او", "أو", "ثم", "أن", "ان", "كان", "كانت", "يكون",
    "يمكن", "هل", "لدي", "لديك", "عندي", "عندك", "اليوم", "جدا",
    "جداً", "بعض", "شيء", "شي", "كيف", "بهذا", "ذلك",
}

# كلمات يمكن حذفها أيضًا لأنها لا تضيف كثيرًا للمطابقة الموضوعية.
GENERIC_WORDS = STOP_WORDS | {
    "مرحبا", "مرحبًا", "اهلا", "أهلا", "اهلاً", "أهلاً",
    "صباح", "مساء", "شكرا", "شكرًا", "نعم", "بالتأكيد",
}


def normalize_arabic(text: str) -> str:
    text = str(text or "")
    text = unicodedata.normalize("NFKC", text)

    text = text.replace("**", "")
    text = ARABIC_DIACRITICS.sub("", text)

    text = text.translate(
        str.maketrans(
            {
                "أ": "ا",
                "إ": "ا",
                "آ": "ا",
                "ٱ": "ا",
                "ى": "ي",
                "ؤ": "و",
                "ئ": "ي",
                "ة": "ه",
            }
        )
    )

    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = MULTI_SPACE.sub(" ", text).strip().lower()

    return text


def stem_arabic(word: str) -> str:
    # Lightweight Arabic normalization for common prefixes/suffixes.
    prefixes = ("وال", "بال", "كال", "فال", "لل", "ال")
    suffixes = ("كما", "كم", "كن", "نا", "ها", "هم", "هن", "ه", "ي", "ك", "ات", "ون", "ين")

    w = word

    if len(w) > 5:
        for prefix in prefixes:
            if w.startswith(prefix) and len(w) - len(prefix) >= 3:
                w = w[len(prefix):]
                break

    if len(w) > 4:
        for suffix in suffixes:
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[:-len(suffix)]
                break

    return w


def content_words(text: str) -> set[str]:
    normalized = normalize_arabic(text)
    words = normalized.split()

    return {
        stem_arabic(word)
        for word in words
        if len(stem_arabic(word)) >= 2 and word not in GENERIC_WORDS
    }


def _extract_turns(dialogue: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []

    for raw_line in dialogue.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        match = SPEAKER_LINE.match(line)

        if not match:
            continue

        speaker, text = match.groups()

        speaker = speaker.replace("**", "").strip()
        text = text.replace("**", "").strip()

        if text:
            turns.append(
                {
                    "speaker": speaker,
                    "text": text,
                    "normalized": normalize_arabic(text),
                }
            )

    return turns


def build_index() -> dict[str, Any]:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Dataset not found: {DATA_FILE}")

    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    with DATA_FILE.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            dialogue = (row.get("dialogue") or "").strip()
            turns = _extract_turns(dialogue)

            for current, following in zip(turns, turns[1:]):
                question = current["text"].strip()
                answer = following["text"].strip()
                normalized = current["normalized"]

                if not normalized or not answer:
                    continue

                key = (normalized, answer)

                if key in seen:
                    continue

                seen.add(key)

                pairs.append(
                    {
                        "q": question,
                        "qn": normalized,
                        "words": sorted(content_words(question)),
                        "a": answer,
                        "topic": str(row.get("topic") or "").strip(),
                    }
                )

    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": 2,
        "source": DATA_FILE.name,
        "pairs": pairs,
    }

    with INDEX_FILE.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    return payload


def _load_index() -> dict[str, Any]:
    # Version 2 is required because the index now contains content words.
    if not INDEX_FILE.exists():
        return build_index()

    try:
        with INDEX_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if data.get("version") != 2:
            return build_index()

        return data

    except (OSError, json.JSONDecodeError):
        return build_index()


SHORT_CHAT_REPLIES = {
    "كيفك": "تمام الحمدلله 😄 وإنت كيفك؟",
    "كيف حالك": "تمام الحمدلله 😄 وإنت كيفك؟",
    "شو اخبارك": "تمام، كلشي منيح 😄 شو أخبارك إنت؟",
    "شو اخبارك لارا": "تمام، كلشي منيح 😄 شو أخبارك إنت؟",
    "شو عامل": "ولا شي، موجود معك 😄 شو الأخبار؟",
    "شو عم تعمل": "موجود هون وعم بحكي معك 😄",
    "وينك": "هون معك 😄",
    "يسعد صباحك": "يسعد صباحك 🌷",
    "صباح الخير": "صباح النور 🌷",
    "مرحبا": "أهلا وسهلا 😄",
    "اهلا": "أهلا فيك 😄",
    "هاي": "هاي 😄 كيفك؟",
}


def short_chat_answer(text: str) -> str | None:
    query = normalize_arabic(text).strip()
    answer = SHORT_CHAT_REPLIES.get(query)
    if answer is None:
        return None
    # Keep the established reply among a small set of local natural variants.
    variants = {
        "كيفك": ["منيحة الحمدلله 😄 وإنت كيفك؟", "تمام، مبسوطة إني عم بحكي معك 🌷"],
        "كيف حالك": ["منيحة الحمدلله 😄 وإنت كيفك؟", "تمام، مبسوطة إني عم بحكي معك 🌷"],
        "شو اخبارك": ["منيحة، شكرًا لسؤالك 😄", "كلشي تمام! شو أخبارك إنت؟ 🌷"],
        "شو اخبارك لارا": ["منيحة، شكرًا لسؤالك 😄", "كلشي تمام! شو أخبارك إنت؟ 🌷"],
        "شو عامل": ["موجودة هون وجاهزة أحكي معك 😄", "ولا شي، عم برد على أسئلتك 🌷"],
        "شو عم تعمل": ["موجودة هون وجاهزة أحكي معك 😄", "عم بحكي معك هلق 😄"],
        "وينك": ["هون يا أهلا 😄", "موجودة، شو في؟ 🌷"],
        "صباح الخير": ["صباح الورد 🌷", "يسعد صباحك بكل خير ☀️"],
        "مرحبا": ["أهلا فيك! شو الأخبار؟ 😄", "يا مية أهلا 🌷"],
        "اهلا": ["أهلا فيك! شو الأخبار؟ 😄", "يا مية أهلا 🌷"],
        "هاي": ["هاي 😄 شو أخبارك؟", "أهلا، كيفك اليوم؟ 🌷"],
    }
    return random.choice([answer, *variants.get(query, [])])


class ArSyraEngine:
    def __init__(self, threshold: int = DEFAULT_THRESHOLD):
        self.threshold = threshold
        self.data = _load_index()
        self.pairs: list[dict[str, Any]] = self.data.get("pairs", [])

        self.questions = [item["qn"] for item in self.pairs]

        self._choices: dict[str, list[int]] = {}

        for index, question in enumerate(self.questions):
            self._choices.setdefault(question, []).append(index)

        self._unique_questions = list(self._choices.keys())

    @property
    def size(self) -> int:
        return len(self.pairs)

    def _score_candidate(
        self,
        query: str,
        query_words: set[str],
        matched_question: str,
        base_score: float,
    ) -> float | None:
        candidate_words = content_words(matched_question)

        if not query_words:
            return None

        common = query_words & candidate_words

        # No meaningful word in common = almost certainly unrelated.
        if not common:
            return None

        query_coverage = len(common) / len(query_words)
        candidate_coverage = len(common) / max(1, len(candidate_words))

        ratio = fuzz.ratio(query, matched_question)
        token_sort = fuzz.token_sort_ratio(query, matched_question)

        # Strongly reward meaningful shared words.
        score = (
            (base_score * 0.25)
            + (ratio * 0.20)
            + (token_sort * 0.20)
            + (query_coverage * 100 * 0.25)
            + (candidate_coverage * 100 * 0.10)
        )

        # If the user's meaningful vocabulary barely appears, reject it.
        if query_coverage < 0.34 and len(query_words) >= 3:
            return None

        # A very short shared fragment should not beat a substantially
        # more relevant candidate.
        if len(common) == 1 and len(query_words) >= 4:
            return None

        return score

    def answer(self, text: str) -> dict[str, Any] | None:
        query = normalize_arabic(text)
        query_words = content_words(query)

        if not query or not self.pairs or not query_words:
            return None

        # Exact normalized question.
        exact_indices = self._choices.get(query)

        if exact_indices:
            item = self.pairs[exact_indices[0]]

            return {
                "answer": item["a"],
                "score": 100.0,
                "question": item["q"],
                "topic": item["topic"],
            }

        # Retrieve a wider candidate pool using several scorers.
        candidate_map: dict[str, float] = {}

        for scorer in (
            fuzz.ratio,
            fuzz.token_sort_ratio,
            fuzz.token_set_ratio,
        ):
            results = process.extract(
                query,
                self._unique_questions,
                scorer=scorer,
                limit=15,
            )

            for matched, score, _ in results:
                previous = candidate_map.get(matched, 0.0)
                candidate_map[matched] = max(previous, float(score))

        best: tuple[float, dict[str, Any]] | None = None

        for matched_question, base_score in candidate_map.items():
            final_score = self._score_candidate(
                query,
                query_words,
                matched_question,
                base_score,
            )

            if final_score is None:
                continue

            indices = self._choices[matched_question]

            # If the same question occurs several times, choose the first
            # answer for now. This keeps behavior deterministic.
            item = self.pairs[indices[0]]

            if final_score < self.threshold:
                continue

            candidate = (final_score, item)

            if best is None or candidate[0] > best[0]:
                best = candidate

        if best is None:
            return None

        score, item = best

        return {
            "answer": item["a"],
            "score": round(score, 2),
            "question": item["q"],
            "topic": item["topic"],
        }


_engine: ArSyraEngine | None = None


def get_engine() -> ArSyraEngine:
    global _engine

    if _engine is None:
        _engine = ArSyraEngine()

    return _engine


def ask(text: str) -> str | None:
    short_reply = short_chat_answer(text)
    if short_reply is not None:
        return short_reply

    result = get_engine().answer(text)
    if result is None:
        return None

    return result["answer"]

if __name__ == "__main__":
    engine = get_engine()

    print("ArSyra index ready")
    print(f"Pairs: {engine.size}")
    print(f"Threshold: {engine.threshold}")

    tests = [
        "كيف حالك اليوم؟",
        "ما هي أكبر التحديات التي تواجهها في حياتي اليومية؟",
        "كيف أتعامل مع ضغوط العمل؟",
        "ما تأثير التكنولوجيا على مستقبل العمل؟",
        "ما هي عاصمة فرنسا؟",
        "شو أخبارك؟",
    ]

    for query in tests:
        result = engine.answer(query)

        print(f"\nQ: {query}")

        if result:
            print(f"Score: {result['score']}")
            print(f"Matched: {result['question']}")
            print(f"A: {result['answer']}")
        else:
            print("NO MATCH")
