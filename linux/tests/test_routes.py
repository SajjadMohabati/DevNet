"""Route model and the diff that keeps the kernel table in sync."""

from __future__ import annotations

import unittest
from unittest import mock

from devnet.network import RouteEntry
from devnet.routes import Config, Route, RouteStore


def make_store(routes, gateway: str = "") -> RouteStore:
    store = object.__new__(RouteStore)
    store.config = Config(gateway=gateway, routes=routes)
    store.lan_gateway = "192.168.1.1"
    store.lan_device = "wlan0"
    store.lan_ip = "192.168.1.50"
    store.hits = {}
    return store


def ops_for(store: RouteStore, table=None, remove=()):
    with mock.patch("devnet.routes.routing_table", return_value=table or {}):
        return store._plan(
            [
                (route.enabled is True, list(route.targets), store.gateway_for(route))
                for route in store.config.routes
            ],
            list(remove),
        )


class RouteModelTest(unittest.TestCase):
    def test_cidr_targets(self) -> None:
        route = Route("10.20.30.9/24")
        self.assertEqual(route.targets, ["10.20.30.0/24"])
        self.assertFalse(route.is_domain)
        self.assertFalse(route.is_list)

    def test_domain_targets(self) -> None:
        route = Route("portal.example.com", resolved=["1.2.3.4", "1.2.3.5"])
        self.assertTrue(route.is_domain)
        self.assertEqual(route.targets, ["1.2.3.4/32", "1.2.3.5/32"])
        self.assertEqual(Route("portal.example.com").targets, [])

    def test_country_list_targets(self) -> None:
        route = Route("Iran IP ranges", ranges=["1.0.0.0/24", "2.0.0.0/24"])
        self.assertTrue(route.is_list)
        self.assertEqual(route.targets, ["1.0.0.0/24", "2.0.0.0/24"])

    def test_round_trip_keeps_optional_fields(self) -> None:
        route = Route(
            "portal.example.com",
            gateway="192.168.1.1",
            note="Intranet",
            resolved=["1.2.3.4"],
            country="ir",
            enabled=True,
        )
        copy = Route.from_dict(route.to_dict())
        self.assertEqual(copy.to_dict(), route.to_dict())
        self.assertTrue(copy.enabled)
        self.assertEqual(copy.resolved, ["1.2.3.4"])

    def test_config_round_trip(self) -> None:
        config = Config(
            gateway="192.168.1.2",
            routes=[
                Route("10.0.0.0/8", enabled=False),
                Route("Iran IP ranges", ranges=["1.0.0.0/24"], country="ir", enabled=True),
            ],
        )
        copy = Config.from_dict(config.to_dict())
        self.assertEqual(copy.gateway, "192.168.1.2")
        self.assertEqual([route.to_dict() for route in copy.routes], [route.to_dict() for route in config.routes])
        self.assertEqual(Config.from_dict({"routes": ["bad", 1, None]}).routes, [])


class PlanTest(unittest.TestCase):
    def test_adds_route_that_is_missing(self) -> None:
        route = Route("10.20.0.0/16", enabled=True)
        store = make_store([route])
        self.assertEqual(
            ops_for(store),
            [
                {
                    "op": "replace",
                    "cidr": "10.20.0.0/16",
                    "gateway": "192.168.1.1",
                    "device": "wlan0",
                }
            ],
        )

    def test_does_nothing_when_path_is_already_correct(self) -> None:
        route = Route("10.20.0.0/16", enabled=True)
        store = make_store([route])
        table = {
            "10.20.0.0/16": RouteEntry(
                "10.20.0.0/16", gateway="192.168.1.1", device="wlan0"
            )
        }
        self.assertEqual(ops_for(store, table), [])

    def test_replaces_route_on_other_path(self) -> None:
        route = Route("10.20.0.0/16", enabled=True)
        store = make_store([route])
        table = {
            "10.20.0.0/16": RouteEntry(
                "10.20.0.0/16", gateway="10.8.0.1", device="tun0"
            )
        }
        self.assertEqual(
            ops_for(store, table),
            [
                {
                    "op": "replace",
                    "cidr": "10.20.0.0/16",
                    "gateway": "192.168.1.1",
                    "device": "wlan0",
                }
            ],
        )

    def test_drops_cached_host_route_inside_enabled_network(self) -> None:
        route = Route("10.20.0.0/16", enabled=True)
        store = make_store([route])
        table = {
            "10.20.1.9/32": RouteEntry(
                "10.20.1.9/32", gateway="10.8.0.1", device="tun0"
            )
        }
        operations = ops_for(store, table)
        self.assertEqual(
            operations,
            [
                {
                    "op": "replace",
                    "cidr": "10.20.0.0/16",
                    "gateway": "192.168.1.1",
                    "device": "wlan0",
                },
                {
                    "op": "delete",
                    "cidr": "10.20.1.9/32",
                    "gateway": "10.8.0.1",
                    "device": "tun0",
                },
            ],
        )

    def test_drops_new_cached_host_route_when_network_is_already_correct(self) -> None:
        route = Route("10.20.0.0/16", enabled=True)
        store = make_store([route])
        table = {
            "10.20.0.0/16": RouteEntry(
                "10.20.0.0/16", gateway="192.168.1.1", device="wlan0"
            ),
            "10.20.1.9/32": RouteEntry(
                "10.20.1.9/32", gateway="10.8.0.1", device="tun0"
            ),
        }
        self.assertEqual(
            ops_for(store, table),
            [
                {
                    "op": "delete",
                    "cidr": "10.20.1.9/32",
                    "gateway": "10.8.0.1",
                    "device": "tun0",
                }
            ],
        )

    def test_disabled_route_removes_only_an_explicit_gateway(self) -> None:
        route = Route("10.20.0.0/16", enabled=False)
        store = make_store([route])
        table = {
            "10.20.0.0/16": RouteEntry(
                "10.20.0.0/16", gateway="192.168.1.1", device="wlan0"
            ),
            "10.30.0.0/16": RouteEntry("10.30.0.0/16", device="wg0"),
        }
        self.assertEqual(
            ops_for(store, table),
            [
                {
                    "op": "delete",
                    "cidr": "10.20.0.0/16",
                    "gateway": "192.168.1.1",
                    "device": "wlan0",
                }
            ],
        )

    def test_ignores_route_without_gateway(self) -> None:
        route = Route("10.20.0.0/16", enabled=True)
        store = make_store([route])
        store.lan_gateway = ""
        self.assertEqual(ops_for(store), [])

    def test_duplicate_targets_are_collapsed(self) -> None:
        route = Route("10.20.0.0/16", enabled=True)
        route.ranges = ["10.20.0.0/16", "10.20.0.9/16"]
        store = make_store([route])
        self.assertEqual(len(ops_for(store)), 1)

    def test_route_specific_gateway_uses_its_device(self) -> None:
        route = Route("10.20.0.0/16", gateway="10.8.0.1", enabled=True)
        store = make_store([route])
        with mock.patch("devnet.routes.route_get", return_value={"dev": "tun0"}):
            operations = ops_for(store)
        self.assertEqual(operations[0]["gateway"], "10.8.0.1")
        self.assertEqual(operations[0]["device"], "tun0")

    def test_also_remove_deletes_stale_target(self) -> None:
        store = make_store([])
        table = {
            "10.40.0.0/16": RouteEntry(
                "10.40.0.0/16", gateway="192.168.1.1", device="wlan0"
            )
        }
        operations = ops_for(store, table, remove=["10.40.0.0/16"])
        self.assertEqual(
            operations,
            [
                {
                    "op": "delete",
                    "cidr": "10.40.0.0/16",
                    "gateway": "192.168.1.1",
                    "device": "wlan0",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
