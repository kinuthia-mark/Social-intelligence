"""Tests for sign-up, sign-in and the cookie-based JWT check.

The browser never calls these endpoints directly (Next.js does), but the
contract is the same: register/login return a token pair as JSON, and every
other endpoint reads the access token from the `access_token` cookie.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from intel.models import TeamUser

User = get_user_model()


class RegisterTests(APITestCase):
    def test_register_creates_user_profile_and_returns_tokens(self):
        res = self.client.post(
            "/api/auth/register",
            {"name": "Jane Wanjiru", "email": "jane@example.com", "password": "a-long-password"},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

        profile = TeamUser.objects.get(email="jane@example.com")
        self.assertEqual(profile.initials, "JW")
        self.assertEqual(profile.role, "analyst")

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user(username="jane@example.com", email="jane@example.com", password="x")
        res = self.client.post(
            "/api/auth/register",
            {"name": "Jane", "email": "JANE@example.com", "password": "a-long-password"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.data)


class LoginTests(APITestCase):
    def setUp(self):
        User.objects.create_user(username="sam@example.com", email="sam@example.com", password="right-password")

    def test_login_with_email_returns_tokens(self):
        res = self.client.post(
            "/api/auth/login", {"email": "sam@example.com", "password": "right-password"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)

    def test_wrong_password_is_rejected(self):
        res = self.client.post(
            "/api/auth/login", {"email": "sam@example.com", "password": "wrong"}, format="json"
        )
        self.assertEqual(res.status_code, 401)


class CookieAuthTests(APITestCase):
    def setUp(self):
        res = self.client.post(
            "/api/auth/register",
            {"name": "Ali Hassan", "email": "ali@example.com", "password": "a-long-password"},
            format="json",
        )
        self.access = res.data["access"]
        self.refresh = res.data["refresh"]

    def test_me_requires_the_cookie(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_me_works_with_the_cookie(self):
        self.client.cookies["access_token"] = self.access
        res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["email"], "ali@example.com")

    def test_bearer_header_alone_is_not_accepted(self):
        # Tokens only travel in httpOnly cookies, so a header is ignored.
        res = self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(res.status_code, 401)

    def test_logout_blacklists_the_refresh_token(self):
        res = self.client.post("/api/auth/logout", {"refresh": self.refresh}, format="json")
        self.assertEqual(res.status_code, 205)
        res = self.client.post("/api/auth/refresh", {"refresh": self.refresh}, format="json")
        self.assertEqual(res.status_code, 401)
