"""The data assistant behind /api/assistant.

Questions are routed by keyword to a handler, and every handler answers
from the database (mentions, influencers, crises), so the numbers in the
reply always match what the rest of the app shows. Nothing is sent to an
outside AI service.
"""
from __future__ import annotations

from collections import Counter

from .models import Crisis, Influencer, Mention
from .sentiment import analyze

PLATFORM_NAMES = {
    "twitter": "X / Twitter", "instagram": "Instagram", "tiktok": "TikTok",
    "reddit": "Reddit", "linkedin": "LinkedIn", "news": "News / Web", "youtube": "YouTube",
}


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _sentiment_counts(mentions) -> Counter:
    return Counter(m.sentiment for m in mentions)


def sentiment_summary() -> dict:
    mentions = list(Mention.objects.all())
    total = len(mentions)
    counts = _sentiment_counts(mentions)
    pos, neg = counts.get("positive", 0), counts.get("negative", 0)
    neu = total - pos - neg
    topics = Counter(t for m in mentions if m.sentiment == "positive" for t in m.topics)
    driver = topics.most_common(1)[0][0] if topics else "n/a"
    worry = Counter(t for m in mentions if m.sentiment == "negative" for t in m.topics)
    worry_topic = worry.most_common(1)[0][0] if worry else None

    content = (
        f"Across the {total} tracked mentions, sentiment is {_pct(pos, total)}% positive, "
        f"{_pct(neu, total)}% neutral or mixed and {_pct(neg, total)}% negative. "
        f"The most common topic in positive posts is \"{driver}\"."
    )
    if worry_topic:
        content += f" The negative side is driven mostly by \"{worry_topic}\"."
    return {
        "content": content,
        "cards": [
            {"t": "Net sentiment", "v": f"{_pct(pos, total) - _pct(neg, total):+d}", "s": "pos minus neg", "intent": "positive" if pos >= neg else "critical"},
            {"t": "Top driver", "v": driver, "s": f"{topics[driver] if topics else 0} positive posts", "intent": "positive"},
            {"t": "Negative", "v": f"{_pct(neg, total)}%", "s": f"{neg} of {total} mentions", "intent": "warning" if neg else "positive"},
        ],
        "sources": ["Mentions · all platforms"],
    }


def influencers() -> dict:
    top = list(Influencer.objects.order_by("-score")[:3])
    if not top:
        return fallback()
    lead = top[0]
    content = (
        f"The strongest voice right now is {lead.name} ({lead.handle}) with {lead.reach} reach "
        f"and an impact score of {lead.score}. "
    )
    negatives = [i for i in Influencer.objects.all() if i.sentiment == "negative"]
    if negatives:
        n = negatives[0]
        content += f"Keep an eye on {n.handle}: large reach ({n.reach}) but currently negative."
    return {
        "content": content,
        "cards": [
            {"t": i.handle, "v": i.reach, "s": f"reach · {i.sentiment}", "intent": "critical" if i.sentiment == "negative" else "positive"}
            for i in top
        ],
        "sources": ["Analytics · Influencer impact"],
    }


def risks() -> dict:
    flagged = []
    for m in Mention.objects.all():
        result = analyze(m.content)
        if result.risks or m.priority == "critical":
            flagged.append((m, result))

    crisis = Crisis.objects.exclude(status__in=["resolved", "closed"]).first()
    terms = Counter(term for _, r in flagged for term in r.risks)

    if not flagged and not crisis:
        return {
            "content": "No risk terms (recall, contamination, lawsuit, unsafe and similar) appear in current mentions, and there is no active incident.",
            "cards": [{"t": "Risk", "v": "Low", "s": "nothing flagged", "intent": "positive"}],
            "sources": ["Mentions", "Crisis Center"],
        }

    n = len(flagged)
    parts = [f"{n} mention{'s' if n != 1 else ''} {'contain' if n != 1 else 'contains'} risk language or {'are' if n != 1 else 'is'} marked critical."]
    if terms:
        parts.append("Most frequent risk terms: " + ", ".join(f"\"{t}\" ({c})" for t, c in terms.most_common(3)) + ".")
    if crisis:
        parts.append(f"There is an open incident: \"{crisis.title}\" (crisis score {crisis.score}).")
    return {
        "content": " ".join(parts),
        "cards": [
            {"t": f"\"{t}\"", "v": str(c), "s": "mentions", "intent": "critical"} for t, c in terms.most_common(2)
        ] or [{"t": "Critical mentions", "v": str(len(flagged)), "s": "need review", "intent": "critical"}],
        "sources": ["Mentions · risk scan", "Crisis Center"],
        "action": {"label": "Open Crisis Center", "href": "/crisis"},
    }


def platforms() -> dict:
    mentions = list(Mention.objects.all())
    by_platform = Counter(m.platform for m in mentions)
    neg_by_platform = Counter(m.platform for m in mentions if m.sentiment == "negative")
    top, count = by_platform.most_common(1)[0]
    content = (
        f"{PLATFORM_NAMES.get(top, top)} has the most mentions ({count} of {len(mentions)}). "
        + (
            f"Negative posts are concentrated on {PLATFORM_NAMES.get(neg_by_platform.most_common(1)[0][0])}."
            if neg_by_platform else "No platform has a cluster of negative posts."
        )
    )
    return {
        "content": content,
        "cards": [
            {"t": PLATFORM_NAMES.get(p, p), "v": str(c), "s": f"{neg_by_platform.get(p, 0)} negative", "intent": "warning" if neg_by_platform.get(p) else "positive"}
            for p, c in by_platform.most_common(3)
        ],
        "sources": ["Mentions · by platform"],
    }


def engagement_tips() -> dict:
    unanswered = Mention.objects.filter(status="new").count()
    positive_new = Mention.objects.filter(status="new", sentiment="positive").count()
    return {
        "content": (
            f"There are {unanswered} mentions nobody has picked up yet, {positive_new} of them positive. "
            "Replying to positive posts while they are still climbing is the cheapest engagement you can get, "
            "and creator posts are worth asking to reshare. Assign the negative ones first so they get a response before they spread."
        ),
        "cards": [
            {"t": "Unassigned", "v": str(unanswered), "s": "mentions", "intent": "warning" if unanswered else "positive"},
            {"t": "Positive to amplify", "v": str(positive_new), "s": "reply or reshare", "intent": "positive"},
        ],
        "sources": ["Mentions · status = new"],
    }


def fallback() -> dict:
    total = Mention.objects.count()
    neg = Mention.objects.filter(sentiment="negative").count()
    return {
        "content": (
            f"I'm tracking {total} mentions right now, {neg} of them negative. "
            "Ask me about sentiment, influencers, risks, platforms or how to improve engagement."
        ),
        "cards": [
            {"t": "Mentions", "v": str(total), "s": "tracked", "intent": "positive"},
            {"t": "Negative", "v": str(neg), "s": "mentions", "intent": "warning" if neg else "positive"},
        ],
        "sources": ["Overview"],
    }


# Checked in order; the first keyword match wins.
ROUTES = [
    (("risk", "crisis", "threat", "danger", "recall", "problem"), risks),
    (("influencer", "creator", "advocate", "who is driving", "accounts"), influencers),
    (("platform", "channel", "twitter", "instagram", "tiktok", "reddit", "where"), platforms),
    (("improve", "strategy", "strategies", "engagement", "grow", "tips"), engagement_tips),
    (("sentiment", "feel", "audience", "summar", "think", "mood", "campaign"), sentiment_summary),
]


def reply(prompt: str) -> dict:
    text = (prompt or "").lower()
    for keywords, handler in ROUTES:
        if any(k in text for k in keywords):
            return handler()
    return fallback()
