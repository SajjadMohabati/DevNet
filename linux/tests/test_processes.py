"""Dev-server discovery helpers."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devnet.processes import (
    Container,
    DevProcess,
    _listener_ports,
    runtime_glyph,
)


class ContainerTest(unittest.TestCase):
    def test_published_ports(self) -> None:
        container = Container(
            id="abc",
            name="web",
            image="nginx",
            status="Up 2 minutes",
            ports="0.0.0.0:8080->80/tcp, [::]:5432->5432/tcp, 127.0.0.1:3000->3000/tcp",
        )
        self.assertEqual(container.published_ports, [3000, 5432, 8080])

    def test_invalid_port_mappings_are_ignored(self) -> None:
        container = Container(id="abc", name="web", image="nginx", status="Up", ports="80/tcp, :::->80")
        self.assertEqual(container.published_ports, [])

    def test_runtime(self) -> None:
        self.assertEqual(Container("a", "b", "c", "d", runtime="podman").runtime, "podman")


class RuntimeGlyphTest(unittest.TestCase):
    def test_known_runtimes(self) -> None:
        self.assertEqual(runtime_glyph("node"), ("JS", "green"))
        self.assertEqual(runtime_glyph("python3"), ("Py", "blue"))
        self.assertEqual(runtime_glyph("uvicorn"), ("Py", "blue"))
        self.assertEqual(runtime_glyph("dockerd"), ("Dk", "blue"))
        self.assertEqual(runtime_glyph("postgres"), ("Pg", "blue"))

    def test_fallback(self) -> None:
        self.assertEqual(runtime_glyph("mystery"), ("My", "gray"))
        self.assertEqual(runtime_glyph(""), ("??", "gray"))


class ListenerTest(unittest.TestCase):
    def test_ss_lines_are_grouped_by_pid(self) -> None:
        output = "\n".join(
            (
                'LISTEN 0 511 127.0.0.1:3000 0.0.0.0:* users:(("node",pid=1234,fd=22))',
                'LISTEN 0 128 0.0.0.0:3001 0.0.0.0:* users:(("node",pid=1234,fd=25))',
                'LISTEN 0 128 [::1]:5432 [::]:* users:(("postgres",pid=4321,fd=6))',
                'LISTEN 0 128 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=999,fd=6))',
            )
        )
        result = subprocess.CompletedProcess(["ss"], 0, output, "")
        with mock.patch("devnet.processes.run", return_value=result), mock.patch(
            "devnet.processes._same_user", return_value=True
        ):
            found = _listener_ports()
        self.assertEqual(found[1234], ("node", [3000, 3001]))
        self.assertEqual(found[4321], ("postgres", [5432]))

    def test_lines_without_processes_are_skipped(self) -> None:
        result = subprocess.CompletedProcess(
            ["ss"], 0, "LISTEN 0 128 0.0.0.0:80 0.0.0.0:*\n", ""
        )
        with mock.patch("devnet.processes.run", return_value=result):
            self.assertEqual(_listener_ports(), {})


class DevProcessTest(unittest.TestCase):
    def test_project_name_and_subtitle(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "my-app"
            path.mkdir()
            process = DevProcess(pid=10, name="node", ports=[3000], cwd=str(path))
            self.assertTrue(process.has_project)
            self.assertEqual(process.project, "my-app")
            self.assertEqual(process.subtitle, "node")
            self.assertEqual(process.runtime, ("JS", "green"))

    def test_gradle_and_system_paths_have_no_project(self) -> None:
        gradle = DevProcess(pid=10, name="java", cwd="/home/me/.gradle/daemon/8.7")
        self.assertFalse(gradle.has_project)
        self.assertEqual(gradle.project, "Gradle Daemon 8.7")
        system = DevProcess(pid=11, name="nginx", cwd="/usr/sbin")
        self.assertFalse(system.has_project)
        self.assertEqual(system.project, "nginx")

    def test_systemd_unit_subtitle(self) -> None:
        process = DevProcess(pid=10, name="python", unit="devnet-test.service")
        self.assertEqual(process.subtitle, "systemd user unit devnet-test.service")


if __name__ == "__main__":
    unittest.main()
