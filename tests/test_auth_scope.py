"""Cookie host filtering. No browser and no network."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import auth  # noqa: E402


def _cookie(name, value, host):
    return (name, value, host)


class CookieScopeTests(unittest.TestCase):
    def test_exact_host_keeps_only_md_pss_id(self):
        token = auth.select_md_pss_id(
            [
                _cookie("sid", "other", "app.example.com"),
                _cookie("md_pss_id", "session-a", "app.example.com"),
                _cookie("md_pss_id", "session-b", "other.example.com"),
            ],
            "app.example.com",
        )
        self.assertEqual(token, "session-a")

    def test_sibling_host_is_not_attached(self):
        token = auth.select_md_pss_id(
            [_cookie("md_pss_id", "session-b", "other.example.com")],
            "app.example.com",
        )
        self.assertEqual(token, "")

    def test_parent_domain_must_be_explicit(self):
        cookies = [_cookie("md_pss_id", "parent-session", ".example.com")]
        self.assertEqual(auth.select_md_pss_id(cookies, "app.example.com"), "")
        self.assertEqual(
            auth.select_md_pss_id(cookies, "app.example.com", parent_domain="example.com"),
            "parent-session",
        )

    def test_bare_registrable_domain_with_multiple_hosts_is_refused(self):
        cookies = [
            _cookie("md_pss_id", "a", "a.example.com"),
            _cookie("md_pss_id", "b", "b.example.com"),
        ]
        with self.assertRaises(auth.CookieScopeError):
            auth.select_md_pss_id(cookies, "example.com")

    def test_bare_domain_with_one_host_can_match_exactly(self):
        token = auth.select_md_pss_id(
            [_cookie("md_pss_id", "only", "example.com")],
            "example.com",
        )
        self.assertEqual(token, "only")

    def test_multiple_values_for_one_host_are_refused(self):
        cookies = [
            _cookie("md_pss_id", "one", "app.example.com"),
            _cookie("md_pss_id", "two", "app.example.com"),
        ]
        with self.assertRaises(auth.CookieScopeError):
            auth.select_md_pss_id(cookies, "app.example.com")


if __name__ == "__main__":
    unittest.main()
