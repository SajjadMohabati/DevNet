"""The GUI-side half of the privileged helper contract."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devnet import privilege


def completed(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["cmd"], code, stdout, stderr)


class ErrorMessageTest(unittest.TestCase):
    def test_known_polkit_codes(self) -> None:
        self.assertEqual(privilege._error_for(completed(0)), "")
        self.assertIn("dismissed", privilege._error_for(completed(126)))
        self.assertIn("Enable Passwordless Mode", privilege._error_for(completed(127)))
        self.assertIn("Authorization failed", privilege._error_for(completed(125)))

    def test_uses_last_stderr_line(self) -> None:
        self.assertEqual(
            privilege._error_for(completed(1, stderr="noise\nreal problem\n")),
            "real problem",
        )
        self.assertIn("exit 42", privilege._error_for(completed(42)))


class HelperPathTest(unittest.TestCase):
    def test_environment_override(self) -> None:
        with mock.patch.dict(os.environ, {"DEVNET_HELPER": "/tmp/helper"}):
            self.assertEqual(privilege.helper_path(), Path("/tmp/helper"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(privilege.helper_path(), privilege.HELPER)


class PasswordlessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.rule = Path(self.temp.name) / "50-devnet.rules"
        self.patch = mock.patch.object(privilege, "POLKIT_RULE", self.rule)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def write_rule(self, text: str) -> None:
        self.rule.write_text(text, encoding="utf-8")

    def test_rule_for_current_user(self) -> None:
        self.write_rule(
            f"""/* DevNet */
polkit.addRule(function(action, subject) {{
    if (action.id !== "org.freedesktop.policykit.exec") return;
    if (subject.user !== "alice") return;
    if (action.lookup("program") !== "{privilege.HELPER}") return;
    return polkit.Result.YES;
}});
"""
        )
        with mock.patch.dict(os.environ, {"USER": "alice"}):
            self.assertTrue(privilege.passwordless())

    def test_rule_for_another_user_is_not_accepted(self) -> None:
        self.write_rule(
            f"""/* DevNet */
polkit.addRule(function(action, subject) {{
    if (action.id !== "org.freedesktop.policykit.exec") return;
    if (subject.user !== "bob") return;
    if (action.lookup("program") !== "{privilege.HELPER}") return;
    return polkit.Result.YES;
}});
"""
        )
        with mock.patch.dict(os.environ, {"USER": "alice"}):
            self.assertFalse(privilege.passwordless())

    def test_missing_rule(self) -> None:
        with mock.patch.dict(os.environ, {"USER": "alice"}):
            self.assertFalse(privilege.passwordless())

    def test_rule_must_target_the_exec_action_and_helper(self) -> None:
        with mock.patch.dict(os.environ, {"USER": "alice"}):
            self.write_rule('subject.user !== "alice"')
            self.assertFalse(privilege.passwordless())

            self.write_rule(
                'org.freedesktop.policykit.exec\n'
                'subject.user !== "alice"\n'
                'action.lookup("program") !== "/usr/bin/not-devnet"\n'
                '/* DevNet */'
            )
            self.assertFalse(privilege.passwordless())


if __name__ == "__main__":
    unittest.main()
