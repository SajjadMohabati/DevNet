"""Unit tests for the dependency-free root helper."""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HELPER_FILE = Path(__file__).resolve().parents[1] / "data" / "devnet-helper"
LOADER = importlib.machinery.SourceFileLoader("devnet_helper", str(HELPER_FILE))
SPEC = importlib.util.spec_from_loader("devnet_helper", LOADER)
helper = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(helper)


class ValidationTest(unittest.TestCase):
    def test_ipv4(self) -> None:
        self.assertEqual(helper.ipv4(" 192.168.1.1 "), "192.168.1.1")
        for value in ("", "1.2.3", "999.1.1.1", None, 42):
            with self.subTest(value=value):
                with self.assertRaises(helper.HelperError):
                    helper.ipv4(value)

    def test_cidr_is_strict(self) -> None:
        self.assertEqual(helper.cidr("10.20.30.0/24"), "10.20.30.0/24")
        for value in ("10.20.30.5/24", "10.0.0.0/33", "nope"):
            with self.subTest(value=value):
                with self.assertRaises(helper.HelperError):
                    helper.cidr(value)

    def test_interface(self) -> None:
        self.assertEqual(helper.interface("wlan0.100"), "wlan0.100")
        for value in ("", "-bad", "a" * 16, "bad name", None):
            with self.subTest(value=value):
                with self.assertRaises(helper.HelperError):
                    helper.interface(value)

    def test_servers_are_deduplicated(self) -> None:
        self.assertEqual(
            helper.validated_servers(["1.1.1.1", "1.1.1.1", "8.8.8.8"]),
            ["1.1.1.1", "8.8.8.8"],
        )
        self.assertEqual(helper.validated_servers(None), [])
        with self.assertRaises(helper.HelperError):
            helper.validated_servers(["1.1.1.1"] * (helper.MAX_SERVERS + 1))

    def test_operations(self) -> None:
        operations = helper.validated_operations(
            [
                {"op": "replace", "cidr": "10.0.0.0/24", "gateway": "192.168.1.1", "device": "eth0"},
                {"op": "delete", "cidr": "10.1.0.0/16", "gateway": "10.8.0.1", "device": "tun0"},
            ]
        )
        self.assertEqual(operations[0]["op"], "replace")
        self.assertEqual(operations[1]["cidr"], "10.1.0.0/16")

    def test_bad_operations(self) -> None:
        cases = (
            "not a list",
            [None],
            [{"op": "add", "cidr": "10.0.0.0/24", "gateway": "1.2.3.4", "device": "eth0"}],
            [{"op": "replace", "cidr": "bad", "gateway": "1.2.3.4", "device": "eth0"}],
            [{"op": "replace", "cidr": "10.0.0.0/24", "gateway": "bad", "device": "eth0"}],
            [{"op": "replace", "cidr": "10.0.0.0/24", "gateway": "1.2.3.4", "device": "-bad"}],
            [{"op": "replace", "cidr": "10.0.0.0/24", "gateway": "1.2.3.4"}],
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(helper.HelperError):
                    helper.validated_operations(value)


class RequestTest(unittest.TestCase):
    def test_reads_owned_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "request.json"
            path.write_text(json.dumps({"servers": ["1.1.1.1"]}), encoding="utf-8")
            self.assertEqual(helper.read_request(str(path)), {"servers": ["1.1.1.1"]})

    def test_rejects_relative_missing_and_wrong_shape(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "request.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(helper.HelperError):
                helper.read_request("request.json")
            with self.assertRaises(helper.HelperError):
                helper.read_request(str(path))
            with self.assertRaises(helper.HelperError):
                helper.read_request(str(Path(folder) / "missing.json"))

    def test_no_request_is_an_empty_dict(self) -> None:
        self.assertEqual(helper.read_request(None), {})


class RuleTest(unittest.TestCase):
    def test_rule_is_scoped_to_user_and_program(self) -> None:
        text = helper.passwordless_rule("alice")
        self.assertIn('action.id !== "org.freedesktop.policykit.exec"', text)
        self.assertIn('subject.user !== "alice"', text)
        self.assertIn('action.lookup("program") !== "/usr/libexec/devnet/devnet-helper"', text)
        self.assertEqual(text.count("polkit.Result.YES"), 1)

    def test_quote_in_user_name_is_json_escaped(self) -> None:
        self.assertIn('subject.user !== "a\\"b"', helper.passwordless_rule('a"b'))

    def test_skip_dns_links(self) -> None:
        for name in ("lo", "docker0", "veth12", "virbr0", "br-1234", "podman1"):
            self.assertTrue(helper.skip_dns_link(name), name)
        for name in ("wlan0", "tun0", "enp3s0"):
            self.assertFalse(helper.skip_dns_link(name), name)


class ResolvConfRewriteTest(unittest.TestCase):
    def test_replaces_nameservers_and_keeps_options(self) -> None:
        original = b"# generated\nnameserver 9.9.9.9\nsearch lan\noptions edns0\n"
        result = helper.resolv_conf_with_servers(original, ["1.1.1.1", "8.8.8.8"]).decode()
        self.assertNotIn("9.9.9.9", result)
        self.assertIn("nameserver 1.1.1.1\n", result)
        self.assertIn("nameserver 8.8.8.8\n", result)
        self.assertIn("search lan\noptions edns0\n", result)
        self.assertIn("# BEGIN DEVNET", result)
        self.assertIn("# END DEVNET", result)

    def test_removes_an_older_devnet_block(self) -> None:
        original = (
            b"# BEGIN DEVNET\nnameserver 1.1.1.1\n# END DEVNET\n"
            b"nameserver 9.9.9.9\nsearch lan\n"
        )
        result = helper.resolv_conf_with_servers(original, ["8.8.8.8"]).decode()
        self.assertEqual(result.count("# BEGIN DEVNET"), 1)
        self.assertNotIn("9.9.9.9", result)

    def test_any_ip_accepts_v4_and_v6(self) -> None:
        self.assertEqual(helper.any_ip("1.1.1.1"), "1.1.1.1")
        self.assertEqual(helper.any_ip("2001:db8::1"), "2001:db8::1")
        self.assertIsNone(helper.any_ip("not-an-ip"))


class RouteBatchTest(unittest.TestCase):
    def test_batch_input(self) -> None:
        operations = [
            {"op": "replace", "cidr": "10.0.0.0/24", "gateway": "192.168.1.1", "device": "wlan0"},
            {"op": "delete", "cidr": "10.1.0.0/16", "gateway": "10.8.0.1", "device": "tun0"},
        ]
        result = subprocess.CompletedProcess(["ip"], 0, "", "")
        with mock.patch.object(helper, "run", return_value=result) as run:
            helper.apply_routes(operations)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["ip", "-4", "-batch", "-"])
        self.assertEqual(
            kwargs["input_text"],
            "route replace 10.0.0.0/24 via 192.168.1.1 dev wlan0\n"
            "route delete 10.1.0.0/16 via 10.8.0.1 dev tun0\n",
        )

    def test_benign_errors_are_ignored(self) -> None:
        operations = [
            {"op": "replace", "cidr": "10.0.0.0/24", "gateway": "192.168.1.1", "device": "wlan0"}
        ]
        result = subprocess.CompletedProcess(
            ["ip"], 1, "", "RTNETLINK answers: File exists\n"
        )
        with mock.patch.object(helper, "run", return_value=result):
            helper.apply_routes(operations)

    def test_real_errors_are_reported(self) -> None:
        operations = [
            {"op": "replace", "cidr": "10.0.0.0/24", "gateway": "192.168.1.1", "device": "wlan0"}
        ]
        result = subprocess.CompletedProcess(
            ["ip"], 2, "", "Error: Nexthop has invalid gateway.\n"
        )
        with mock.patch.object(helper, "run", return_value=result):
            with self.assertRaises(helper.HelperError) as raised:
                helper.apply_routes(operations)
        self.assertIn("invalid gateway", str(raised.exception))

    def test_empty_operation_list_does_nothing(self) -> None:
        with mock.patch.object(helper, "run") as run:
            helper.apply_routes([])
        run.assert_not_called()


class NetworkManagerBackupTest(unittest.TestCase):
    def test_apply_saves_servers_and_ignore_flag(self) -> None:
        saved = {}

        def capture(value):
            saved.update(value)

        ok = subprocess.CompletedProcess(["nmcli"], 0, "", "")
        with (
            mock.patch.object(helper, "nm_devices", return_value=["eth0"]),
            mock.patch.object(helper, "nm_dns_for_device", return_value=["9.9.9.9"]),
            mock.patch.object(helper, "nm_ignore_auto", return_value="yes"),
            mock.patch.object(helper, "load_dns_backup", return_value=None),
            mock.patch.object(helper, "save_dns_backup", side_effect=capture),
            mock.patch.object(helper, "run", return_value=ok),
        ):
            helper.apply_network_manager(["1.1.1.1"])
        self.assertEqual(saved["backend"], "NetworkManager")
        self.assertEqual(saved["devices"]["eth0"], {"servers": ["9.9.9.9"], "ignore_auto": "yes"})

    def test_restore_puts_profile_back_before_reapply(self) -> None:
        backup = {
            "backend": "NetworkManager",
            "devices": {"eth0": {"servers": ["9.9.9.9"], "ignore_auto": "yes"}},
        }
        ok = subprocess.CompletedProcess(["nmcli"], 0, "", "")
        with (
            mock.patch.object(helper, "nm_devices", return_value=["eth0"]),
            mock.patch.object(helper, "run", return_value=ok) as run,
        ):
            helper.restore_network_manager(backup)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            calls[0],
            ["nmcli", "device", "modify", "eth0", "ipv4.dns", "9.9.9.9",
             "ipv4.ignore-auto-dns", "yes"],
        )
        self.assertEqual(calls[1], ["nmcli", "device", "reapply", "eth0"])

    def test_restore_clears_servers_when_none_were_saved(self) -> None:
        backup = {
            "backend": "NetworkManager",
            "devices": {"wlan0": {"servers": [], "ignore_auto": "no"}},
        }
        ok = subprocess.CompletedProcess(["nmcli"], 0, "", "")
        with (
            mock.patch.object(helper, "nm_devices", return_value=["wlan0"]),
            mock.patch.object(helper, "run", return_value=ok) as run,
        ):
            helper.restore_network_manager(backup)
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["nmcli", "device", "modify", "wlan0", "ipv4.dns", "",
             "ipv4.ignore-auto-dns", "no"],
        )


class MainTest(unittest.TestCase):
    def test_version(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(helper.main(["--version"]), 0)
        self.assertIn("devnet-helper", output.getvalue())

    def test_unknown_action(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(helper.main(["nope"]), 2)
        self.assertIn("Unknown action", error.getvalue())

    def test_usage_without_arguments(self) -> None:
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(helper.main([]), 2)
        self.assertIn("usage:", error.getvalue())


if __name__ == "__main__":
    unittest.main()
