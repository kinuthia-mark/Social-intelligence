"""Lexicon-based sentiment and risk analysis for short social posts.

No model download or API key is needed. Each word is looked up in small
hand-tuned lexicons, with three adjustments that matter a lot for social
media text:

* negation   - "not good" counts as negative ("not", "never", "no", "n't")
* intensity  - "really good" and "SO GOOD" count more than "good"
* emoji      - common emoji carry sentiment of their own

The result is a positive / neutral / negative split, a confidence score,
the strongest emotions, the topics (hashtags and repeated keywords) and
any brand-risk terms such as "recall" or "lawsuit".
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

POSITIVE = {
    "love": 3, "loved": 3, "loving": 3, "obsessed": 3, "amazing": 3, "awesome": 3, "best": 3,
    "excellent": 3, "fantastic": 3, "incredible": 3, "perfect": 3, "favourite": 2, "favorite": 2,
    "great": 2, "good": 2, "nice": 1, "happy": 2, "glad": 2, "delicious": 3, "tasty": 2,
    "refreshing": 2, "recommend": 2, "recommended": 2, "works": 1, "worth": 2, "beautiful": 2,
    "fresh": 1, "smooth": 1, "clean": 1, "fast": 1, "helpful": 2, "thanks": 1, "thank": 1,
    "impressed": 2, "enjoy": 2, "enjoyed": 2, "win": 2, "wins": 2, "genuinely": 1, "trust": 2,
    "safe": 1, "healthy": 1, "restock": 1, "finally": 1, "wow": 2, "fan": 2,
}

NEGATIVE = {
    "hate": -3, "hated": -3, "awful": -3, "terrible": -3, "worst": -3, "disgusting": -3,
    "horrible": -3, "bad": -2, "poor": -2, "disappointed": -2, "disappointing": -2,
    "overpriced": -2, "expensive": -1, "sick": -2, "ill": -2, "gross": -2, "broken": -2,
    "fake": -2, "scam": -3, "lie": -2, "lies": -2, "lying": -2, "unsafe": -3, "dangerous": -3,
    "contaminated": -3, "contamination": -3, "recall": -2, "recalled": -2, "rumor": -1,
    "rumour": -1, "angry": -2, "annoyed": -2, "slow": -1, "rude": -2, "waste": -2,
    "refund": -1, "complaint": -2, "problem": -1, "issue": -1, "worried": -2, "fear": -2,
    "scary": -2, "boycott": -3, "lawsuit": -3, "sugar": -1, "wtf": -2, "meh": -1, "never": 0,
}

EMOJI = {
    "😍": 3, "❤️": 3, "❤": 3, "💛": 2, "🙌": 2, "🔥": 2, "😊": 2, "👍": 2, "✨": 1, "🥰": 3,
    "😋": 2, "😂": 1, "😡": -3, "🤮": -3, "😤": -2, "👎": -2, "😞": -2, "💀": -1, "🙄": -2,
}

NEGATORS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wasnt", "wasn't", "cant", "can't", "nothing", "hardly"}
INTENSIFIERS = {"very": 1.5, "really": 1.5, "so": 1.4, "super": 1.5, "extremely": 1.8, "genuinely": 1.3, "absolutely": 1.7, "literally": 1.2}

EMOTIONS = {
    "Joy": {"love", "loved", "happy", "obsessed", "amazing", "delicious", "enjoy", "enjoyed", "wow", "best", "great"},
    "Trust": {"trust", "safe", "recommend", "recommended", "genuinely", "works", "reliable", "official"},
    "Anticipation": {"finally", "restock", "soon", "waiting", "launch", "new", "coming"},
    "Fear": {"fear", "scary", "unsafe", "dangerous", "worried", "sick", "contamination", "contaminated", "recall"},
    "Anger": {"hate", "angry", "annoyed", "rude", "scam", "boycott", "worst", "wtf"},
    "Disgust": {"disgusting", "gross", "awful", "horrible"},
    "Distrust": {"fake", "lie", "lies", "lying", "rumor", "rumour", "true", "official", "source"},
}

# Words that suggest a reputational or legal problem, whatever the tone.
RISK_TERMS = {
    "recall", "recalled", "contamination", "contaminated", "lawsuit", "sue", "suing", "boycott",
    "unsafe", "dangerous", "sick", "hospital", "scam", "fraud", "allergic", "allergy", "lawyer",
    "investigation", "fda", "kebs",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "it", "its",
    "this", "that", "to", "of", "in", "on", "for", "with", "my", "i", "im", "i'm", "you", "your",
    "we", "our", "they", "their", "at", "as", "have", "has", "had", "just", "so", "me", "do",
    "does", "did", "not", "no", "all", "any", "about", "from", "what", "who", "how", "than",
    "then", "there", "here", "out", "up", "if", "can", "will", "would", "every", "single", "time",
    "one", "actually", "really", "very", "get", "got", "don't", "dont", "anyone", "seen",
}

_TOKEN = re.compile(r"#\w+|@\w+|[a-zA-Z']+")


@dataclass
class Analysis:
    label: str
    positive: int
    neutral: int
    negative: int
    score: float
    confidence: int
    emotions: list[dict] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    positive_phrases: list[str] = field(default_factory=list)
    negative_phrases: list[str] = field(default_factory=list)


def _phrase(tokens: list[str], i: int) -> str:
    start = max(0, i - 2)
    return '"' + " ".join(tokens[start:i + 1]) + '"'


def analyze(text: str) -> Analysis:
    raw_tokens = _TOKEN.findall(text or "")
    tokens = [t.lower() for t in raw_tokens]

    pos_total = 0.0
    neg_total = 0.0
    pos_phrases: list[str] = []
    neg_phrases: list[str] = []

    for i, tok in enumerate(tokens):
        word = tok.lstrip("#")
        value = POSITIVE.get(word) or NEGATIVE.get(word) or 0
        if not value:
            continue

        # Look back up to three words for a negator or intensifier.
        window = tokens[max(0, i - 3):i]
        if any(w in NEGATORS for w in window):
            value = -value * 0.75
        for w in window:
            value *= INTENSIFIERS.get(w, 1.0)
        if raw_tokens[i].isupper() and len(raw_tokens[i]) > 2:
            value *= 1.3  # SHOUTING

        if value > 0:
            pos_total += value
            pos_phrases.append(_phrase(tokens, i))
        else:
            neg_total += -value
            neg_phrases.append(_phrase(tokens, i))

    for emoji, value in EMOJI.items():
        count = text.count(emoji) if text else 0
        if count:
            if value > 0:
                pos_total += value * count
            else:
                neg_total += -value * count

    # Exclamation marks amplify whatever the dominant tone is.
    if text and "!" in text:
        boost = 1 + min(text.count("!"), 3) * 0.1
        if pos_total >= neg_total:
            pos_total *= boost
        else:
            neg_total *= boost

    signal = pos_total + neg_total
    # Neutral share shrinks as the text carries more sentiment words.
    neutral_weight = max(1.0, len(tokens) / 4)
    total = signal + neutral_weight
    positive = round(100 * pos_total / total)
    negative = round(100 * neg_total / total)
    neutral = 100 - positive - negative

    score = 0.0 if signal == 0 else (pos_total - neg_total) / signal  # -1 .. 1
    if signal == 0 or abs(score) < 0.2:
        label = "mixed" if pos_total and neg_total else "neutral"
    else:
        label = "positive" if score > 0 else "negative"

    confidence = int(min(98, 50 + abs(score) * 30 + min(signal, 10) * 2)) if signal else 55

    emotion_counts = Counter()
    for word in (t.lstrip("#") for t in tokens):
        for emotion, words in EMOTIONS.items():
            if word in words:
                emotion_counts[emotion] += 1
    top = emotion_counts.most_common(3)
    peak = top[0][1] if top else 1
    emotions = [{"k": k, "v": min(95, int(40 + 55 * c / peak) - i * 8)} for i, (k, c) in enumerate(top)]

    hashtags = [t for t in raw_tokens if t.startswith("#")]
    keywords = Counter(
        t for t in tokens
        if not t.startswith(("#", "@")) and t not in STOPWORDS and len(t) > 3
        and t not in POSITIVE and t not in NEGATIVE
    )
    topics = list(dict.fromkeys(hashtags + [w for w, _ in keywords.most_common(5)]))[:6]

    risks = sorted({t.lstrip("#") for t in tokens if t.lstrip("#") in RISK_TERMS})

    return Analysis(
        label=label,
        positive=positive,
        neutral=neutral,
        negative=negative,
        score=round(score, 2),
        confidence=confidence,
        emotions=emotions,
        topics=topics,
        risks=risks,
        positive_phrases=list(dict.fromkeys(pos_phrases))[:4],
        negative_phrases=list(dict.fromkeys(neg_phrases))[:4],
    )
