"""Credential-free API smoke tests for Harbour."""

import unittest

from fastapi.testclient import TestClient

from app import app


class HarbourApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_home_is_rebranded(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Harbour", response.text)
        self.assertIn("From uncertainty to a clear next step.", response.text)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_intake(self):
        response = self.client.post(
            "/api/intake",
            json={"transcript": "I lost my job and need food this week"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("food", response.json()["needs"])

    def test_match(self):
        response = self.client.post(
            "/api/match",
            json={"needs": ["food"], "urgency": "this_week"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["tracking_number"].startswith("HARBOUR-"))
        self.assertGreater(len(payload["plan"]), 0)

    def test_fairness_demo(self):
        response = self.client.get("/api/demo")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertLessEqual(payload["fair"]["parity_gap"], 0.10)

    def test_batch_demo_uses_neutral_labels(self):
        response = self.client.get("/api/batch/run")
        self.assertEqual(response.status_code, 200)
        groups = {person["group"] for person in response.json()["people"]}
        self.assertEqual(groups, {"Central District", "Outer District"})

    def test_chat_works_without_api_key(self):
        response = self.client.post(
            "/api/chat",
            json={"message": "Hello", "plan": [], "language": "English"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "rules")
        self.assertTrue(response.json()["reply"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
