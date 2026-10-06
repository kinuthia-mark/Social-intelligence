"""Dashboard aggregates computed from MentionEvent rows.

Every number on the overview and analytics screens comes from here: KPIs,
volume and engagement series, sentiment and platform splits, hashtags,
trends, weekly sentiment, the live feed and the brand health score.
Periods are rolling windows ending now, so "this week" is the last 7 days
and "last week" the 7 days before that.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from .models import MentionEvent

RANGE_DAYS = {"today": 7, "7d": 7, "30d": 30, "90d": 90, "custom": 30}

PLATFORM_LABELS = {
    "twitter": "X / Twitter", "instagram": "Instagram", "tiktok": "TikTok",
    "reddit": "Reddit", "news": "News / Web",
}
PLATFORM_COLORS = {
    "twitter": "#6366f1", "instagram": "#a855f7", "tiktok": "#22d3ee",
    "reddit": "#f97316", "news": "#64748b",
}


# --- formatting helpers ------------------------------------------------------

def compact(n: float) -> str:
    """48210 -> '48.2K', 12400000 -> '12.4M'."""
    for size, suffix in ((1_000_000, "M"), (1_000, "K")):
        if abs(n) >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{int(n)}"


def pct_change(now: float, before: float) -> str:
    if not before:
        return "new" if now else "0%"
    change = (now - before) / before * 100
    return f"{change:+.1f}%" if abs(change) < 100 else f"{change:+.0f}%"


def pt_change(now: float, before: float) -> str:
    diff = round(now - before, 1)
    sign = "+" if diff >= 0 else "−"
    return f"{sign}{abs(diff):g}pt"


def share(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


# --- windows -----------------------------------------------------------------

def _window(days: int, offset_days: int = 0, now: datetime | None = None):
    now = now or timezone.now()
    end = now - timedelta(days=offset_days)
    return MentionEvent.objects.filter(created_at__gt=end - timedelta(days=days), created_at__lte=end)


def _stats(qs) -> dict:
    agg = qs.aggregate(n=Count("id"), reach=Sum("reach"), engagement=Sum("engagement"))
    n = agg["n"] or 0
    reach = agg["reach"] or 0
    by_sentiment = Counter(qs.values_list("sentiment", flat=True))
    responded = qs.filter(responded=True).count()
    return {
        "mentions": n,
        "reach": reach,
        "engagement_rate": share(agg["engagement"] or 0, reach),
        "positive": share(by_sentiment.get("positive", 0), n),
        "negative": share(by_sentiment.get("negative", 0), n),
        "response": share(responded, n),
    }


def _daily(days: int, now: datetime | None = None) -> list[dict]:
    """One bucket per rolling 24 hours for the last `days` days, oldest first.

    Rolling windows (rather than calendar days) mean the newest bucket is
    always a full day, so charts never end in a half-empty "today".
    """
    now = now or timezone.now()
    buckets = [{"mentions": 0, "positive": 0, "negative": 0, "reach": 0, "engagement": 0} for _ in range(days)]
    rows = MentionEvent.objects.filter(created_at__gt=now - timedelta(days=days), created_at__lte=now).values_list(
        "created_at", "sentiment", "reach", "engagement")
    for created, sentiment, reach, engagement in rows:
        idx = days - 1 - int((now - created).total_seconds() // 86400)
        b = buckets[idx]
        b["mentions"] += 1
        b["reach"] += reach
        b["engagement"] += engagement
        if sentiment in ("positive", "negative"):
            b[sentiment] += 1
    return [{"day": (now - timedelta(days=days - 1 - i)).date(), **b} for i, b in enumerate(buckets)]


def _label(day) -> str:
    return f"{day:%b} {day.day}"


# --- endpoints -----------------------------------------------------------------

def kpis(now: datetime | None = None) -> list[dict]:
    this, last = _stats(_window(7, 0, now)), _stats(_window(7, 7, now))
    daily = _daily(10, now)

    def spark(key):
        if key == "mentions":
            return [d["mentions"] for d in daily]
        if key == "reach":
            return [round(d["reach"] / 1000, 1) for d in daily]
        if key == "engagement":
            return [share(d["engagement"], d["reach"]) for d in daily]
        if key == "positive":
            return [share(d["positive"], d["mentions"]) for d in daily]
        return []

    def intent(good: bool) -> str:
        return "positive" if good else "warning"

    response_spark = []
    for i in range(9, -1, -1):
        response_spark.append(_stats(_window(1, i, now))["response"])

    return [
        {"id": "mentions", "label": "Mentions (7d)", "value": compact(this["mentions"]),
         "delta": pct_change(this["mentions"], last["mentions"]), "intent": intent(this["mentions"] >= last["mentions"]),
         "spark": spark("mentions")},
        {"id": "reach", "label": "Est. reach (7d)", "value": compact(this["reach"]),
         "delta": pct_change(this["reach"], last["reach"]), "intent": intent(this["reach"] >= last["reach"]),
         "spark": spark("reach")},
        {"id": "engagement", "label": "Engagement", "value": f"{this['engagement_rate']:g}%",
         "delta": pt_change(this["engagement_rate"], last["engagement_rate"]),
         "intent": intent(this["engagement_rate"] >= last["engagement_rate"]), "spark": spark("engagement")},
        {"id": "positive", "label": "Positive sent.", "value": f"{round(this['positive'])}%",
         "delta": pt_change(this["positive"], last["positive"]), "intent": intent(this["positive"] >= last["positive"]),
         "spark": spark("positive")},
        {"id": "response", "label": "Response rate", "value": f"{round(this['response'])}%",
         "delta": pt_change(this["response"], last["response"]), "intent": intent(this["response"] >= last["response"]),
         "spark": response_spark},
    ]


def health_score(stats: dict) -> int:
    """0-100. Weighted mix of positive share, response rate and absence of negativity."""
    score = 0.55 * stats["positive"] + 0.30 * stats["response"] + 0.15 * (100 - 3 * stats["negative"])
    return max(0, min(100, round(score)))


def brand_health(now: datetime | None = None) -> dict:
    this, last = _stats(_window(7, 0, now)), _stats(_window(7, 7, now))
    score, before = health_score(this), health_score(last)
    if score >= 75:
        status, intent = "HEALTHY", "positive"
    elif score >= 50:
        status, intent = "AT RISK", "warning"
    else:
        status, intent = "CRITICAL", "critical"
    diff = score - before
    arrow = "▲" if diff >= 0 else "▼"

    top = _window(7, 0, now).order_by("-reach").first()
    drivers = [
        {"label": "Negative share this week", "value": pt_change(this["negative"], last["negative"]),
         "intent": "critical" if this["negative"] > last["negative"] else "positive"},
        {"label": f"Top post ({PLATFORM_LABELS.get(top.platform, top.platform)})" if top else "Top post",
         "value": compact(top.reach) if top else "0", "intent": "warning" if top and top.sentiment == "negative" else "positive"},
        {"label": "Mentions vs last week", "value": pct_change(this["mentions"], last["mentions"]),
         "intent": "positive" if this["mentions"] >= last["mentions"] else "warning"},
    ]
    return {"score": score, "status": status, "intent": intent,
            "deltaLabel": f"{arrow} {abs(diff)} pts this week", "drivers": drivers}


def mention_volume(range_key: str, now: datetime | None = None) -> list[dict]:
    days = RANGE_DAYS.get(range_key, 7)
    return [{"date": _label(d["day"]), "mentions": d["mentions"], "positive": d["positive"], "negative": d["negative"]}
            for d in _daily(days, now)]


def engagement_series(range_key: str, now: datetime | None = None) -> list[dict]:
    days = RANGE_DAYS.get(range_key, 7)
    return [{"date": _label(d["day"]), "interactions": d["engagement"]} for d in _daily(days, now)]


def sentiment_distribution(now: datetime | None = None) -> list[dict]:
    counts = Counter(_window(30, 0, now).values_list("sentiment", flat=True))
    total = sum(counts.values())
    pos, neg = round(share(counts["positive"], total)), round(share(counts["negative"], total))
    return [
        {"name": "Positive", "value": pos, "color": "var(--color-positive)"},
        {"name": "Neutral", "value": 100 - pos - neg if total else 0, "color": "var(--color-neutral)"},
        {"name": "Negative", "value": neg, "color": "var(--color-critical)"},
    ]


def platform_breakdown(now: datetime | None = None) -> list[dict]:
    counts = Counter(_window(30, 0, now).values_list("platform", flat=True))
    total = sum(counts.values())
    return [{"platform": PLATFORM_LABELS.get(p, p), "mentions": round(share(n, total)), "color": PLATFORM_COLORS.get(p, "#64748b")}
            for p, n in counts.most_common()]


def platform_comparison(now: datetime | None = None) -> list[dict]:
    qs = _window(30, 0, now).values("platform").annotate(n=Count("id"), e=Sum("engagement"))
    total_n = sum(r["n"] for r in qs) or 1
    total_e = sum(r["e"] or 0 for r in qs) or 1
    rows = [{"platform": PLATFORM_LABELS.get(r["platform"], r["platform"]).replace(" / Web", ""),
             "mentions": round(100 * r["n"] / total_n), "engagement": round(100 * (r["e"] or 0) / total_e)} for r in qs]
    return sorted(rows, key=lambda r: -r["mentions"])


def _hashtag_counts(days: int, offset: int, now) -> Counter:
    c = Counter()
    for tags in _window(days, offset, now).values_list("hashtags", flat=True):
        c.update(tags)
    return c


def hashtags(now: datetime | None = None) -> list[dict]:
    month = _window(30, 0, now)
    volume, reach = Counter(), Counter()
    for tags, r in month.values_list("hashtags", "reach"):
        for t in tags:
            volume[t] += 1
            reach[t] += r
    this, last = _hashtag_counts(7, 0, now), _hashtag_counts(7, 7, now)
    daily = [_hashtag_counts(1, i, now) for i in range(6, -1, -1)]
    out = []
    for tag, n in volume.most_common(5):
        out.append({
            "tag": tag, "vol": f"{n:,}", "reach": compact(reach[tag]),
            "change": pct_change(this[tag], last[tag]),
            "intent": "critical" if "recall" in tag.lower() else ("positive" if this[tag] >= last[tag] else "warning"),
            "spark": [d[tag] for d in daily],
        })
    return out


def trends(now: datetime | None = None) -> list[dict]:
    """Hashtags ranked by this week's volume, with the change on last week."""
    this, last = _hashtag_counts(7, 0, now), _hashtag_counts(7, 7, now)
    out = []
    for i, (tag, n) in enumerate(this.most_common(4), start=1):
        risky = "recall" in tag.lower()
        out.append({"rank": f"{i:02d}", "term": tag, "vol": compact(n), "change": pct_change(n, last[tag]),
                    "intent": "critical" if risky else ("positive" if n >= last[tag] else "warning")})
    return out


def sentiment_bars(now: datetime | None = None) -> list[dict]:
    """Weekly sentiment split for the last 14 weeks, oldest first."""
    out = []
    for week in range(13, -1, -1):
        counts = Counter(_window(7, week * 7, now).values_list("sentiment", flat=True))
        total = sum(counts.values())
        pos, neg = round(share(counts["positive"], total)), round(share(counts["negative"], total))
        out.append({"week": f"W{14 - week}", "positive": pos, "neutral": max(0, 100 - pos - neg), "negative": neg})
    return out


def _ago(then: datetime, now: datetime) -> str:
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)}m"
    if minutes < 1440:
        return f"{minutes // 60}h"
    return f"{minutes // 1440}d"


def live_feed(now: datetime | None = None, limit: int = 5) -> list[dict]:
    now = now or timezone.now()
    return [
        {"platform": e.platform, "text": f"\"{e.text}\"",
         "meta": f"{PLATFORM_LABELS.get(e.platform, e.platform)} · {compact(e.reach)} reach · {_ago(e.created_at, now)}",
         "sentiment": e.sentiment}
        for e in MentionEvent.objects.filter(created_at__lte=now).order_by("-created_at")[:limit]
    ]
