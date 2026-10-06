"""The data assistant behind /api/assistant.

Questions are routed by keyword to a handler, and every handler answers
from the database (the last 7 days of mention history, influencers, crises,
and the inbox), so the numbers in the
reply always match what the rest of the app shows. Nothing is sent to an
outside AI service.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

from django.utils import timezone

from .models import Crisis, Influencer, Mention, MentionEvent
from .sentiment import analyze


@dataclass
class Post:
    text: str
    sentiment: str
    platform: str
    topics: list


def _recent_posts() -> tuple[list[Post], str]:
    """The last 7 days of mention history, or the inbox if there is no history."""
    since = timezone.now() - timedelta(days=7)
    rows = MentionEvent.objects.filter(created_at__gt=since).values_list("text", "sentiment", "platform", "hashtags")
    posts = [Post(t, s, p, h) for t, s, p, h in rows]
    if posts:
        return posts, "the last 7 days"
    return [Post(m.content, m.sentiment, m.platform, m.topics) for m in Mention.objects.all()], "the inbox"


@lru_cache(maxsize=4096)
def _risk_terms(text: str) -> tuple:
    # Thousands of posts share a few hundred distinct texts, so cache the scan.
    return tuple(analyze(text).risks)

PLATFORM_NAMES = {
    "twitter": "X / Twitter", "instagram": "Instagram", "tiktok": "TikTok",
    "reddit": "Reddit", "linkedin": "LinkedIn", "news": "News / Web", "youtube": "YouTube",
}


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def sentiment_summary() -> dict:
    posts, scope = _recent_posts()
    total = len(posts)
    counts = Counter(p.sentiment for p in posts)
    pos, neg = counts.get("positive", 0), counts.get("negative", 0)
    neu = total - pos - neg
    topics = Counter(t for p in posts if p.sentiment == "positive" for t in p.topics)
    driver = topics.most_common(1)[0][0] if topics else "n/a"
    worry = Counter(t for p in posts if p.sentiment == "negative" for t in p.topics)
    worry_topic = worry.most_common(1)[0][0] if worry else None

    content = (
        f"Across {total:,} mentions in {scope}, sentiment is {_pct(pos, total)}% positive, "
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
            {"t": "Negative", "v": f"{_pct(neg, total)}%", "s": f"{neg:,} of {total:,} mentions", "intent": "warning" if neg else "positive"},
        ],
        "sources": [f"Mentions · {scope}"],
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
    posts, scope = _recent_posts()
    flagged = [(p, _risk_terms(p.text)) for p in posts]
    flagged = [(p, r) for p, r in flagged if r]

    crisis = Crisis.objects.exclude(status__in=["resolved", "closed"]).first()
    terms = Counter(term for _, r in flagged for term in r)

    if not flagged and not crisis:
        return {
            "content": "No risk terms (recall, contamination, lawsuit, unsafe and similar) appear in current mentions, and there is no active incident.",
            "cards": [{"t": "Risk", "v": "Low", "s": "nothing flagged", "intent": "positive"}],
            "sources": ["Mentions", "Crisis Center"],
        }

    n = len(flagged)
    parts = [f"{n:,} of {len(posts):,} mentions in {scope} ({_pct(n, len(posts))}%) contain risk language."]
    if terms:
        parts.append("Most frequent risk terms: " + ", ".join(f"\"{t}\" ({c})" for t, c in terms.most_common(3)) + ".")
    if crisis:
        parts.append(f"There is an open incident: \"{crisis.title}\" (crisis score {crisis.score}).")
    return {
        "content": " ".join(parts),
        "cards": [
            {"t": f"\"{t}\"", "v": f"{c:,}", "s": "mentions", "intent": "critical"} for t, c in terms.most_common(3)
        ] or [{"t": "Open incident", "v": crisis.title if crisis else "-", "s": "Crisis Center", "intent": "critical"}],
        "sources": ["Mentions · risk scan", "Crisis Center"],
        "action": {"label": "Open Crisis Center", "href": "/crisis"},
    }


def platforms() -> dict:
    posts, scope = _recent_posts()
    by_platform = Counter(p.platform for p in posts)
    neg_by_platform = Counter(p.platform for p in posts if p.sentiment == "negative")
    if not by_platform:
        return fallback()
    top, count = by_platform.most_common(1)[0]
    content = f"{PLATFORM_NAMES.get(top, top)} has the most mentions in {scope} ({count:,} of {len(posts):,}). "
    if neg_by_platform:
        worst, n = neg_by_platform.most_common(1)[0]
        content += f"The most negative posts are on {PLATFORM_NAMES.get(worst, worst)} ({n:,})."
    else:
        content += "No platform has a cluster of negative posts."
    return {
        "content": content,
        "cards": [
            {"t": PLATFORM_NAMES.get(p, p), "v": f"{c:,}", "s": f"{neg_by_platform.get(p, 0):,} negative",
             "intent": "warning" if neg_by_platform.get(p, 0) > c * 0.2 else "positive"}
            for p, c in by_platform.most_common(3)
        ],
        "sources": [f"Mentions · by platform, {scope}"],
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
    posts, scope = _recent_posts()
    total = len(posts)
    neg = sum(p.sentiment == "negative" for p in posts)
    return {
        "content": (
            f"I'm tracking {total:,} mentions in {scope}, {neg:,} of them negative. "
            "Ask me about sentiment, influencers, risks, platforms or how to improve engagement."
        ),
        "cards": [
            {"t": "Mentions", "v": f"{total:,}", "s": scope, "intent": "positive"},
            {"t": "Negative", "v": f"{neg:,}", "s": "mentions", "intent": "warning" if neg else "positive"},
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
