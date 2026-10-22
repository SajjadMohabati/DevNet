"""DNS preset parsing and resolver command output."""

from __future__ import annotations

import struct
import unittest

from devnet.dns import (
    DEFAULT_PRESETS,
    DNSPreset,
    DNSStore,
    build_dns_query,
    migrate_presets,
    parse_resolv_conf,
    parse_resolvectl_status,
)


class ResolvConfTest(unittest.TestCase):
    def test_nameservers_and_comments(self) -> None:
        text = """\
# Managed by NetworkManager
nameserver 192.168.1.1
nameserver 1.1.1.1 # primary
nameserver 2001:db8::1
search lan
options edns0
"""
        self.assertEqual(parse_resolv_conf(text), ["192.168.1.1", "1.1.1.1"])

    def test_empty(self) -> None:
        self.assertEqual(parse_resolv_conf(""), [])
        self.assertEqual(parse_resolv_conf("nameserver not-an-ip\n"), [])


class ResolvectlTest(unittest.TestCase):
    def test_links_global_and_default_route(self) -> None:
        text = """\
Global
       Protocols: -LLMNR -mDNS -DNSOverTLS DNSSEC=no/unsupported
       DNS Servers: 1.1.1.1 8.8.8.8

Link 2 (wlan0)
    Current Scopes: DNS
         Protocols: +DefaultRoute
Current DNS Server: 192.168.1.1
       DNS Servers: 192.168.1.1 2001:db8::1
        Default Route: yes

Link 3 (tun0)
       DNS Servers: 10.8.0.1
        Default Route: no
"""
        links, global_servers = parse_resolvectl_status(text)
        self.assertEqual(global_servers, ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(links["wlan0"].servers, ["192.168.1.1"])
        self.assertTrue(links["wlan0"].default_route)
        self.assertEqual(links["tun0"].servers, ["10.8.0.1"])
        self.assertFalse(links["tun0"].default_route)

    def test_empty(self) -> None:
        self.assertEqual(parse_resolvectl_status(""), ({}, []))


class PresetTest(unittest.TestCase):
    def test_default_presets_are_valid(self) -> None:
        self.assertGreater(len(DEFAULT_PRESETS), 4)
        for preset in DEFAULT_PRESETS:
            self.assertTrue(preset.name)
            self.assertTrue(preset.servers)
            self.assertEqual(len(preset.servers), len(set(preset.servers)))

    def test_migrate_shecan_and_add_pro(self) -> None:
        presets = [
            DNSPreset("Shecan", ["178.22.122.100", "185.51.231.231"]),
            DNSPreset("Google", ["8.8.8.8"]),
        ]
        migrate_presets(presets)
        self.assertEqual(presets[0].servers, ["178.22.122.100", "185.51.200.2"])
        self.assertEqual(presets[1].name, "Shecan Pro")
        self.assertEqual(presets[1].servers, ["178.22.122.101", "185.51.200.1"])

    def test_migrate_does_not_duplicate_pro(self) -> None:
        presets = [
            DNSPreset("Shecan", ["178.22.122.100", "185.51.200.2"]),
            DNSPreset("Shecan Pro", ["178.22.122.101", "185.51.200.1"]),
        ]
        migrate_presets(presets)
        self.assertEqual([preset.name for preset in presets], ["Shecan", "Shecan Pro"])

    def test_preset_round_trip_drops_invalid_servers(self) -> None:
        preset = DNSPreset.from_dict(
            {"name": "Mine", "servers": ["1.1.1.1", "bad", "8.8.8.8"], "id": "fixed"}
        )
        self.assertEqual(preset.servers, ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(preset.id, "fixed")
        self.assertEqual(preset.to_dict()["name"], "Mine")


class ActivePresetTest(unittest.TestCase):
    def _store(self, presets, current=(), configured=(), applied=()):
        store = object.__new__(DNSStore)
        store.presets = presets
        store.current = list(current)
        store.configured = list(configured)
        store.applied = list(applied)
        return store

    def test_order_does_not_matter(self) -> None:
        google = DNSPreset("Google", ["8.8.8.8", "8.8.4.4"])
        store = self._store([google], current=["8.8.4.4", "8.8.8.8"])
        self.assertIs(store.active_preset, google)

    def test_falls_back_to_configured_then_applied(self) -> None:
        google = DNSPreset("Google", ["8.8.8.8", "8.8.4.4"])
        store = self._store([google], configured=["8.8.4.4", "8.8.8.8"])
        self.assertIs(store.active_preset, google)
        store = self._store([google], applied=["8.8.8.8", "8.8.4.4"])
        self.assertIs(store.active_preset, google)

    def test_unknown_is_none(self) -> None:
        google = DNSPreset("Google", ["8.8.8.8"])
        store = self._store([google], current=["1.1.1.1"])
        self.assertIsNone(store.active_preset)


class DNSQueryTest(unittest.TestCase):
    def test_header_and_qname(self) -> None:
        query = build_dns_query("example.com")
        transaction, flags, questions, answers, authority, additional = struct.unpack(
            "!HHHHHH", query[:12]
        )
        self.assertEqual(flags, 0x0100)
        self.assertEqual((questions, answers, authority, additional), (1, 0, 0, 0))
        self.assertEqual(query[12:], b"\x07example\x03com\x00\x00\x01\x00\x01")
        self.assertGreaterEqual(transaction, 0)
        self.assertLessEqual(transaction, 0xFFFF)

    def test_empty_host_still_has_a_root_label(self) -> None:
        self.assertTrue(build_dns_query("").endswith(b"\x00\x00\x01\x00\x01"))


if __name__ == "__main__":
    unittest.main()
