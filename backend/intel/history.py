"""Generates the demo brand's mention history.

The story: Vela, a drinks brand, grows steadily over 14 weeks thanks to the
#VelaGlow campaign and a creator collaboration. Two days ago a false
product-recall rumour broke, causing a spike of negative posts that starts
to fade as the team publishes lab results (the incident in the Crisis Center).

Posts are built from templates and labelled by sentiment.analyze(), the same
engine used for pasted text, so the dashboards show what the engine decided
rather than labels typed by hand. A fixed random seed makes every run produce
identical data, which keeps tests and screenshots stable.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from django.utils import timezone

from .models import MentionEvent
from .sentiment import analyze

DAYS = 98  # 14 weeks
PLATFORMS = [("twitter", 38), ("instagram", 24), ("tiktok", 18), ("reddit", 11), ("news", 9)]
REACH = {"twitter": (800, 60000), "instagram": (1500, 90000), "tiktok": (3000, 250000),
         "reddit": (300, 25000), "news": (5000, 400000)}

POSITIVE = [
    "Absolutely love the new Vela Yuzu, best drink I've had all year #VelaGlow",
    "Vela restock finally here, the Yuzu flavour is amazing #YuzuSeason",
    "Genuinely impressed by Vela, it actually works for my afternoon slump #VelaGlow",
    "@tech_maren was right, Vela is so refreshing #VelaXMaren",
    "Great taste and the can design is beautiful #VelaGlow",
    "My favourite wellness drink right now, highly recommend #WellnessDrink",
    "Tried every Vela flavour, Yuzu wins. Delicious #YuzuSeason",
    "Happy to see Vela in my local store finally #VelaGlow",
]
NEUTRAL = [
    "Vela is now stocked at more stores across Nairobi",
    "Has anyone compared Vela with other adaptogen drinks? #WellnessDrink",
    "Vela announced a new flavour for next month",
    "Picked up a Vela Yuzu on the way to work",
    "Vela raises Series B to expand its drinks line",
]
NEGATIVE = [
    "Vela is way too expensive for a small can, disappointed",
    "Why is there so much sugar in Vela, not healthy at all",
    "The Vela delivery was slow and the support was rude",
    "Not impressed with the new Vela flavour, tastes awful",
]
RECALL = [
    "Is the Vela recall real? Heard the Berry batch is contaminated #VelaRecall",
    "Worried about the Vela contamination rumour, anyone know the truth? #VelaRecall",
    "Saw a thread saying people got sick from Vela Berry. Unsafe? #VelaRecall",
    "Boycott Vela until they explain the recall #VelaRecall",
]
RECOVERY = [
    "Vela published the lab results, there is no recall. Glad they were open about it #VelaGlow",
    "Respect to Vela for answering every question about the rumour. Trust restored",
]

RUMOUR_START = 2  # days ago: the rumour broke two days ago and is still live
RUMOUR_PEAK_DAYS = 4


def _daily_volume(days_ago: int, rng: random.Random) -> int:
    growth = 60 + (DAYS - days_ago) * 0.9          # steady campaign growth
    weekend = 0.85 if (days_ago % 7) in (1, 2) else 1.0
    return int(growth * weekend * rng.uniform(0.85, 1.15))


def _rumour_posts(days_ago: int) -> int:
    since = RUMOUR_START - days_ago
    if since < 0:
        return 0
    if since < RUMOUR_PEAK_DAYS:
        return 90 - since * 10
    return max(0, int(55 * (0.72 ** (since - RUMOUR_PEAK_DAYS))))


def build(now: datetime | None = None, seed: int = 7) -> list[MentionEvent]:
    """Returns unsaved MentionEvent rows covering the last DAYS days."""
    rng = random.Random(seed)
    now = now or timezone.now()
    platforms = [p for p, _ in PLATFORMS]
    weights = [w for _, w in PLATFORMS]
    labels: dict[str, str] = {}
    rows: list[MentionEvent] = []

    def add(days_ago: int, text: str, responded_p: float):
        if text not in labels:
            labels[text] = analyze(text).label
        platform = rng.choices(platforms, weights)[0]
        low, high = REACH[platform]
        reach = int(rng.uniform(low, high))
        rows.append(MentionEvent(
            # Spread across the 24 hours that end `days_ago` days before now.
            created_at=now - timedelta(days=days_ago, seconds=rng.randint(0, 86399)),
            platform=platform,
            text=text,
            sentiment=labels[text],
            hashtags=[w for w in text.split() if w.startswith("#")],
            reach=reach,
            engagement=int(reach * rng.uniform(0.02, 0.08)),
            responded=rng.random() < responded_p,
        ))

    for days_ago in range(DAYS - 1, -1, -1):
        # The team's response rate improves across the period.
        responded_p = 0.70 + 0.18 * (DAYS - days_ago) / DAYS
        for _ in range(_daily_volume(days_ago, rng)):
            pool = rng.choices([POSITIVE, NEUTRAL, NEGATIVE], [62, 26, 12])[0]
            add(days_ago, rng.choice(pool), responded_p)
        for _ in range(_rumour_posts(days_ago)):
            add(days_ago, rng.choice(RECALL), responded_p - 0.2)
        if 0 < RUMOUR_START - days_ago < 20:
            for _ in range(rng.randint(2, 6)):
                add(days_ago, rng.choice(RECOVERY), responded_p)

    return rows


def seed_history(now: datetime | None = None) -> int:
    MentionEvent.objects.all().delete()
    rows = build(now)
    MentionEvent.objects.bulk_create(rows, batch_size=2000)
    return len(rows)
