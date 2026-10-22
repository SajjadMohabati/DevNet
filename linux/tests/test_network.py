"""Parsing of ``ip route`` and NetworkManager output."""

from __future__ import annotations

import unittest
from unittest import mock

from devnet.network import (
    NetStore,
    RouteEntry,
    Tunnel,
    _kind_for,
    _split_nmcli,
    default_routes,
    is_tunnel_name,
    is_virtual_name,
    parse_route_get,
    parse_route_line,
    routing_table,
    vpn_active,
)


class RouteLineTest(unittest.TestCase):
    def test_default_route(self) -> None:
        entry = parse_route_line(
            "default via 192.168.1.1 dev wlan0 proto dhcp src 192.168.1.50 metric 600"
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.cidr, "0.0.0.0/0")
        self.assertEqual(entry.gateway, "192.168.1.1")
        self.assertEqual(entry.device, "wlan0")
        self.assertEqual(entry.source, "192.168.1.50")
        self.assertEqual(entry.metric, 600)
        self.assertEqual(entry.protocol, "dhcp")

    def test_network_route_is_canonicalised(self) -> None:
        entry = parse_route_line("10.20.30.9/24 via 192.168.1.1 dev eth0 metric 100")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.cidr, "10.20.30.0/24")

    def test_host_route(self) -> None:
        entry = parse_route_line("10.1.2.3 via 192.168.1.1 dev eth0")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.cidr, "10.1.2.3/32")

    def test_interface_only_route(self) -> None:
        entry = parse_route_line("default dev wg0 scope link")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.device, "wg0")
        self.assertIsNone(entry.gateway)

    def test_ignored_routes(self) -> None:
        for line in (
            "",
            "local 10.0.0.1 dev lo scope host",
            "broadcast 10.0.0.255 dev eth0 table local",
            "unreachable default metric 4278198272",
            "garbage",
        ):
            with self.subTest(line=line):
                self.assertIsNone(parse_route_line(line))

    def test_same_path(self) -> None:
        entry = RouteEntry("10.0.0.0/8", gateway="192.168.1.1", device="eth0")
        self.assertTrue(entry.same_path("192.168.1.1", "eth0"))
        self.assertFalse(entry.same_path("192.168.1.2", "eth0"))
        self.assertFalse(entry.same_path("192.168.1.1", "wlan0"))


class RouteTableTest(unittest.TestCase):
    def test_routing_table_keeps_lowest_metric(self) -> None:
        output = "\n".join(
            (
                "default via 192.168.1.1 dev eth0 metric 600",
                "default via 10.8.0.1 dev tun0 metric 50",
                "10.20.0.0/16 via 192.168.1.1 dev eth0",
                "10.30.0.0/16 via 192.168.1.1 dev eth0",
                "10.30.0.0/16 via 192.168.1.2 dev eth0 metric 20",
                "10.30.0.0/16 via 192.168.1.3 dev eth0 metric 200",
            )
        )
        with mock.patch("devnet.network.sh", return_value=output):
            table = routing_table()
        self.assertEqual(table["0.0.0.0/0"].gateway, "10.8.0.1")
        self.assertEqual(table["10.30.0.0/16"].gateway, "192.168.1.2")

    def test_default_routes_discovers_all_paths(self) -> None:
        output = "\n".join(
            (
                "default via 192.168.1.1 dev eth0 metric 600",
                "default via 10.8.0.1 dev tun0 metric 50",
                "default via 192.168.1.1 dev eth0 metric 600",
            )
        )
        with mock.patch("devnet.network.sh", return_value=output):
            routes = default_routes()
        self.assertEqual(len(routes), 2)
        self.assertEqual({route.device for route in routes}, {"eth0", "tun0"})


class RouteGetTest(unittest.TestCase):
    def test_parse(self) -> None:
        value = parse_route_get(
            "10.20.1.1 via 192.168.1.1 dev wlan0 src 192.168.1.50 uid 1000\n    cache"
        )
        self.assertEqual(value["via"], "192.168.1.1")
        self.assertEqual(value["dev"], "wlan0")
        self.assertEqual(value["src"], "192.168.1.50")
        self.assertEqual(value["uid"], "1000")


class InterfaceNameTest(unittest.TestCase):
    def test_tunnels_and_virtuals(self) -> None:
        for name in ("tun0", "wg0", "ppp0", "tailscale0", "nordlynx"):
            self.assertTrue(is_tunnel_name(name), name)
        self.assertFalse(is_tunnel_name("wlan0"))
        for name in ("docker0", "veth123", "virbr0", "br-1234"):
            self.assertTrue(is_virtual_name(name), name)
        self.assertFalse(is_virtual_name("enp3s0"))


class NmcliTest(unittest.TestCase):
    def test_escaped_colons(self) -> None:
        self.assertEqual(
            _split_nmcli(r"Work\: VPN:uuid-1:vpn:tun0"),
            ["Work: VPN", "uuid-1", "vpn", "tun0"],
        )
        self.assertEqual(_split_nmcli("plain:two:three"), ["plain", "two", "three"])

    def test_kind_mapping(self) -> None:
        self.assertEqual(_kind_for("Proton", "vpn"), "ProtonVPN")
        self.assertEqual(_kind_for("Home", "wireguard"), "WireGuard")
        self.assertEqual(_kind_for("Office", "vpn"), "VPN")


class NetStoreTest(unittest.TestCase):
    def test_vpn_properties(self) -> None:
        store = NetStore()
        self.assertFalse(store.vpn)
        store.tunnels = [Tunnel("Home", "WireGuard", "wg0", "203.0.113.9")]
        self.assertTrue(store.vpn)
        self.assertEqual(store.vpn_ip, "203.0.113.9")
        store.default_iface = "wg0"
        self.assertTrue(store.vpn)
        self.assertEqual(store.vpn_ip, "203.0.113.9")
        store.tunnels = []
        store.default_iface = "eth0"
        store.direct_ip = "198.51.100.2"
        self.assertEqual(store.vpn_ip, "198.51.100.2")
        self.assertTrue(vpn_active("wg0", []))
        self.assertTrue(vpn_active("eth0", [Tunnel("Home", "WireGuard", "wg0")]))


if __name__ == "__main__":
    unittest.main()
