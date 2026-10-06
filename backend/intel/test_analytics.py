"""Tests for the dashboard aggregates in analytics.py and the history generator."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase

from intel import analytics, history
from intel.models import MentionEvent

NOW = datetime(2026, 6, 12, 15, 0, tzinfo=dt_timezone.utc)


class EmptyDatabaseTests(TestCase):
    """A fresh install has no history; nothing may crash or divide by zero."""

    def test_every_aggregate_works_without_data(self):
        self.assertEqual(len(analytics.kpis(NOW)), 5)
        self.assertEqual(analytics.brand_health(NOW)["drivers"][1]["value"], "0")
        self.assertEqual(len(analytics.mention_volume("30d", NOW)), 30)
        self.assertEqual(analytics.platform_breakdown(NOW), [])
        self.assertEqual(analytics.hashtags(NOW), [])
        self.assertEqual(analytics.trends(NOW), [])
        self.assertEqual(len(analytics.sentiment_bars(NOW)), 14)
        self.assertEqual(analytics.live_feed(NOW), [])


class SeededHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MentionEvent.objects.bulk_create(history.build(NOW))

    def week(self, offset=0):
        return MentionEvent.objects.filter(
            created_at__gt=NOW - timedelta(days=7 + offset), created_at__lte=NOW - timedelta(days=offset))

    def test_generator_is_deterministic(self):
        a, b = history.build(NOW), history.build(NOW)
        self.assertEqual([(r.text, r.created_at) for r in a[:50]], [(r.text, r.created_at) for r in b[:50]])

    def test_generated_labels_come_from_the_engine(self):
        from intel.sentiment import analyze
        for row in MentionEvent.objects.all()[:200]:
            self.assertEqual(row.sentiment, analyze(row.text).label)

    def test_mentions_kpi_matches_the_database(self):
        kpi = next(k for k in analytics.kpis(NOW) if k["id"] == "mentions")
        self.assertEqual(kpi["value"], analytics.compact(self.week().count()))
        self.assertEqual(len(kpi["spark"]), 10)

    def test_volume_series_adds_up_to_the_window(self):
        series = analytics.mention_volume("7d", NOW)
        self.assertEqual(len(series), 7)
        self.assertEqual(sum(p["mentions"] for p in series), self.week().count())

    def test_ranges(self):
        self.assertEqual(len(analytics.mention_volume("30d", NOW)), 30)
        self.assertEqual(len(analytics.engagement_series("90d", NOW)), 90)
        self.assertEqual(len(analytics.mention_volume("nonsense", NOW)), 7)

    def test_percentage_splits_add_up_to_100(self):
        self.assertEqual(sum(s["value"] for s in analytics.sentiment_distribution(NOW)), 100)
        for bar in analytics.sentiment_bars(NOW):
            self.assertEqual(bar["positive"] + bar["neutral"] + bar["negative"], 100, bar["week"])

    def test_the_rumour_shows_up_where_it_should(self):
        bars = analytics.sentiment_bars(NOW)
        self.assertGreater(bars[-1]["negative"], 2 * bars[-3]["negative"], "latest week has the negative spike")
        recall = next(t for t in analytics.trends(NOW) if t["term"] == "#VelaRecall")
        self.assertEqual(recall["intent"], "critical")
        health = analytics.brand_health(NOW)
        self.assertIn("▼", health["deltaLabel"])
        self.assertEqual(health["drivers"][0]["intent"], "critical")

    def test_live_feed_is_newest_first(self):
        feed = analytics.live_feed(NOW)
        newest = MentionEvent.objects.filter(created_at__lte=NOW).order_by("-created_at").first()
        self.assertEqual(feed[0]["text"], f'"{newest.text}"')

    def test_health_score_bounds(self):
        self.assertEqual(analytics.health_score({"positive": 100, "response": 100, "negative": 0}), 100)
        self.assertEqual(analytics.health_score({"positive": 0, "response": 0, "negative": 100}), 0)


class FormattingTests(TestCase):
    def test_compact(self):
        self.assertEqual(analytics.compact(950), "950")
        self.assertEqual(analytics.compact(48210), "48.2K")
        self.assertEqual(analytics.compact(12_400_000), "12.4M")
        self.assertEqual(analytics.compact(2000), "2K")

    def test_changes(self):
        self.assertEqual(analytics.pct_change(110, 100), "+10.0%")
        self.assertEqual(analytics.pct_change(5, 0), "new")
        self.assertEqual(analytics.pt_change(58, 62), "−4pt")
