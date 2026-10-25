"""Persistent tests for identity resolution."""

import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOLVER_PATH = Path(__file__).resolve().parent / "resolver.py"

spec = importlib.util.spec_from_file_location(
    "identity_resolver",
    RESOLVER_PATH,
)
resolver_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver_module)

IdentityResolver = resolver_module.IdentityResolver
parse_timestamp = resolver_module.parse_timestamp


class TestIdentityResolver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = IdentityResolver.from_directory(
            PROJECT_ROOT / "dataset"
        )
        cls.cutoff = "2026-10-01T12:00:00Z"

    def test_dataset_loads(self):
        self.assertEqual(len(self.resolver.identities), 850)

    def test_known_historical_email_resolves(self):
        result = self.resolver.resolve_email(
            "abena.o189491@zoho.com",
            self.cutoff,
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["user_id"], "user_35")

    def test_unknown_email_is_unresolved(self):
        result = self.resolver.resolve_email(
            "unknown-test-987654@example.com",
            self.cutoff,
        )
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertIsNone(result["user_id"])

    def test_blank_email_is_unresolved(self):
        result = self.resolver.resolve_email("", self.cutoff)
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertIsNone(result["user_id"])

    def test_duplicate_email_is_ambiguous(self):
        users = [
            {
                "user_id": "test_1",
                "email": "shared@example.com",
                "email_hash": "",
                "phone": "",
            },
            {
                "user_id": "test_2",
                "email": "shared@example.com",
                "email_hash": "",
                "phone": "",
            },
        ]
        resolver = IdentityResolver(users, [])
        result = resolver.resolve_email(
            "shared@example.com",
            self.cutoff,
        )
        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertIsNone(result["user_id"])
        self.assertEqual(len(result["matches"]), 2)

    def test_cutoff_timestamp_parses_as_utc(self):
        timestamp = parse_timestamp(self.cutoff)
        self.assertEqual(timestamp.utcoffset().total_seconds(), 0)

    def test_user_35_latest_state_matches_snapshot(self):
        snapshot = self.resolver.identities["user_35"]
        state = self.resolver._state_at_cutoff(
            "user_35",
            parse_timestamp(self.cutoff),
        )
        for field in ("email", "email_hash", "phone"):
            self.assertEqual(
                state[field].strip().casefold(),
                snapshot[field].strip().casefold(),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
