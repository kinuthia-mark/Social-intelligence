"""Tests for the sentiment engine, text post analysis and the data assistant."""
from django.core.management import call_command
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from intel.models import Mention
from intel.sentiment import analyze


class SentimentEngineTests(SimpleTestCase):
    def test_clear_positive(self):
        result = analyze("I absolutely love this drink, best thing I've tried all year!")
        self.assertEqual(result.label, "positive")
        self.assertGreater(result.positive, result.negative)
        self.assertIn("Joy", [e["k"] for e in result.emotions])

    def test_clear_negative(self):
        result = analyze("Worst purchase ever. It tasted awful and the support was rude.")
        self.assertEqual(result.label, "negative")
        self.assertGreater(result.negative, result.positive)

    def test_negation_flips_the_meaning(self):
        self.assertEqual(analyze("This is good").label, "positive")
        self.assertEqual(analyze("This is not good").label, "negative")

    def test_neutral_text(self):
        result = analyze("The store opens at 9am on Monday.")
        self.assertEqual(result.label, "neutral")
        self.assertEqual(result.neutral, 100)

    def test_mixed_text(self):
        self.assertEqual(analyze("Love the branding, hate the price.").label, "mixed")

    def test_emoji_and_shouting_count(self):
        plain = analyze("good")
        loud = analyze("GOOD 😍😍")
        self.assertGreater(loud.positive, plain.positive)

    def test_risk_terms_are_found(self):
        result = analyze("Got sick after the Berry batch. Is there a recall? Talking to a lawyer.")
        self.assertEqual(result.risks, ["lawyer", "recall", "sick"])

    def test_hashtags_become_topics(self):
        self.assertIn("#VelaGlow", analyze("Loving the new flavour #VelaGlow").topics)

    def test_percentages_add_up(self):
        for text in ["", "great", "terrible", "great but terrible", "a b c d e f g"]:
            r = analyze(text)
            self.assertEqual(r.positive + r.neutral + r.negative, 100, text)

    def test_agrees_with_most_hand_labelled_demo_mentions(self):
        call_command("seed_data", verbosity=0)
        mentions = list(Mention.objects.all())
        agree = sum(analyze(m.content).label == m.sentiment for m in mentions)
        self.assertGreaterEqual(agree / len(mentions), 0.75)

    # seed_data writes to the database, which SimpleTestCase blocks by default.
    databases = {"default"}


class AuthedTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", verbosity=0)

    def setUp(self):
        res = self.client.post("/api/auth/login", {"email": "ochiengs@vela.co", "password": "vela-demo-2026"}, format="json")
        self.client.cookies["access_token"] = res.data["access"]


class PostAnalysisTests(AuthedTestCase):
    def test_pasted_text_is_analysed(self):
        res = self.client.post("/api/post-analysis", {"text": "Got sick from the Berry batch. Awful. #VelaRecall"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["source"], "text")
        self.assertEqual(res.data["label"], "negative")
        self.assertIn("mentions sick", res.data["risks"])
        self.assertEqual(res.data["sentiment"]["positive"] + res.data["sentiment"]["neutral"] + res.data["sentiment"]["negative"], 100)
        self.assertEqual(res.data["recommendations"][0]["title"], "Respond before it spreads")

    def test_positive_text_gets_an_amplify_recommendation(self):
        res = self.client.post("/api/post-analysis", {"text": "Absolutely love the new Yuzu flavour! #VelaGlow"}, format="json")
        self.assertIn("Amplify it", [r["title"] for r in res.data["recommendations"]])

    def test_url_returns_the_sample_post(self):
        res = self.client.post("/api/post-analysis", {"url": "https://x.com/someone/status/1"}, format="json")
        self.assertEqual(res.data["source"], "url")
        self.assertEqual(res.data["url"], "https://x.com/someone/status/1")

    def test_very_long_text_is_rejected(self):
        res = self.client.post("/api/post-analysis", {"text": "a" * 5001}, format="json")
        self.assertEqual(res.status_code, 400)


class AssistantTests(AuthedTestCase):
    def ask(self, prompt):
        res = self.client.post("/api/assistant", {"prompt": prompt}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["role"], "assistant")
        return res.data

    def test_sentiment_answer_uses_real_counts(self):
        from datetime import timedelta
        from django.utils import timezone
        from intel.models import MentionEvent
        total = MentionEvent.objects.filter(created_at__gt=timezone.now() - timedelta(days=7)).count()
        reply = self.ask("Summarize audience sentiment for the last campaign.")
        self.assertIn(f"Across {total:,} mentions in the last 7 days", reply["content"])

    def test_risk_question_finds_the_recall_rumour(self):
        reply = self.ask("Identify emerging risks for our brand.")
        self.assertIn("recall", reply["content"].lower())
        self.assertEqual(reply["action"]["href"], "/crisis")

    def test_influencer_question_names_the_top_creator(self):
        reply = self.ask("Which influencers are driving engagement?")
        self.assertTrue(reply["cards"])
        self.assertIn("@", reply["cards"][0]["t"])

    def test_platform_question(self):
        self.assertIn("mentions", self.ask("Which platform is loudest?")["content"])

    def test_unknown_question_falls_back_to_a_summary(self):
        reply = self.ask("hello there")
        self.assertIn("Ask me about", reply["content"])
