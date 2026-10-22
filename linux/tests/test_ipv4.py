"""IPv4 and domain helpers shared by the Linux port."""

from __future__ import annotations

import unittest

from devnet.ipv4 import (
    first_ipv4,
    ip_string,
    network_contains,
    normalize_cidr,
    normalize_domain,
    parse_cidr,
    parse_ip,
)


class ParseIPTest(unittest.TestCase):
    def test_valid_addresses(self) -> None:
        self.assertEqual(parse_ip("0.0.0.0"), 0)
        self.assertEqual(parse_ip("1.2.3.4"), 0x01020304)
        self.assertEqual(parse_ip("255.255.255.255"), 0xFFFFFFFF)

    def test_invalid_addresses(self) -> None:
        for value in ("", "1.2.3", "1.2.3.4.5", "256.1.1.1", "-1.2.3.4", "1.2.3.x"):
            with self.subTest(value=value):
                self.assertIsNone(parse_ip(value))

    def test_surrounding_space_is_ignored(self) -> None:
        self.assertIsNotNone(parse_ip(" 1.2.3.4 "))

    def test_round_trip(self) -> None:
        for value in ("0.0.0.0", "10.20.30.40", "192.168.1.1", "255.255.255.255"):
            self.assertEqual(ip_string(parse_ip(value)), value)


class CIDRTest(unittest.TestCase):
    def test_canonical_network(self) -> None:
        self.assertEqual(
            parse_cidr("10.20.30.5/24"),
            ("10.20.30.0/24", "10.20.30.0", "255.255.255.0"),
        )
        self.assertEqual(normalize_cidr("10.20.30.9/16"), "10.20.0.0/16")
        self.assertEqual(normalize_cidr("10.1.2.3"), None)

    def test_host_and_default(self) -> None:
        self.assertEqual(parse_cidr("10.1.2.3/32")[0], "10.1.2.3/32")
        self.assertEqual(parse_cidr("0.0.0.0/0"), ("0.0.0.0/0", "0.0.0.0", "0.0.0.0"))

    def test_invalid(self) -> None:
        for value in ("10.0.0.0", "10.0.0.0/33", "10.0.0.0/-1", "x/24", "10.0.0.0/24/8"):
            with self.subTest(value=value):
                self.assertIsNone(parse_cidr(value))


class DomainTest(unittest.TestCase):
    def test_urls_and_ports(self) -> None:
        self.assertEqual(normalize_domain("https://Portal.Example.com/path?q=1"), "portal.example.com")
        self.assertEqual(normalize_domain("intranet.example.com:8443"), "intranet.example.com")
        self.assertEqual(normalize_domain("  example.com  "), "example.com")

    def test_invalid(self) -> None:
        for value in ("localhost", "", "http://", ".example.com", "example.com.", "a..b", "exa mple.com"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_domain(value))


class FirstIPv4Test(unittest.TestCase):
    def test_extracts_from_text_and_json(self) -> None:
        self.assertEqual(first_ipv4("hello 203.0.113.7 world"), "203.0.113.7")
        self.assertEqual(first_ipv4('{"ip":"198.51.100.4"}'), "198.51.100.4")
        self.assertEqual(first_ipv4("999.1.1.1 then 8.8.8.8"), "8.8.8.8")
        self.assertEqual(first_ipv4("no address"), "")


class NetworkContainsTest(unittest.TestCase):
    def test_membership(self) -> None:
        self.assertTrue(network_contains("10.20.0.0/16", "10.20.4.5"))
        self.assertFalse(network_contains("10.20.0.0/16", "10.21.4.5"))
        self.assertFalse(network_contains("not-a-network", "10.20.4.5"))


if __name__ == "__main__":
    unittest.main()
