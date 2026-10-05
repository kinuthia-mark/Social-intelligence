"""Tests for the data API: it must be closed to anonymous callers, and the
main read endpoints must return the seeded demo data."""
from django.core.management import call_command
from rest_framework.test import APITestCase

from intel.models import Mention

READ_ENDPOINTS = [
    "/api/kpis",
    "/api/brand-health",
    "/api/mention-volume?range=7d",
    "/api/sentiment-distribution",
    "/api/platform-breakdown",
    "/api/hashtags",
    "/api/mentions",
    "/api/crises",
    "/api/alerts",
    "/api/alert-rules",
    "/api/reports",
    "/api/team",
    "/api/audit-logs",
]


class AnonymousAccessTests(APITestCase):
    def test_every_data_endpoint_rejects_anonymous_requests(self):
        for url in READ_ENDPOINTS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)


class SeededDataTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)

    def setUp(self):
        res = self.client.post(
            "/api/auth/login",
            {"email": "ochiengs@vela.co", "password": "vela-demo-2026"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, "the seeded demo account should be able to sign in")
        self.client.cookies["access_token"] = res.data["access"]

    def test_every_data_endpoint_answers_for_a_signed_in_user(self):
        for url in READ_ENDPOINTS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_mentions_list_matches_the_database(self):
        res = self.client.get("/api/mentions")
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), Mention.objects.count())
        self.assertGreater(len(rows), 0)
