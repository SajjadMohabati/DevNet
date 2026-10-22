"""Speed-test formatting and result models."""

from __future__ import annotations

import unittest

from devnet.speed import SpeedMeta, SpeedResult, average, format_rate, format_speed


class FormattingTest(unittest.TestCase):
    def test_megabits(self) -> None:
        self.assertEqual(format_speed(0), "0 kbps")
        self.assertEqual(format_speed(1_000), "8 kbps")
        self.assertEqual(format_speed(125_000), "1.00 Mbps")
        self.assertEqual(format_speed(1_000_000), "8.00 Mbps")
        self.assertEqual(format_speed(10_000_000), "80.0 Mbps")
        self.assertEqual(format_speed(125_000_000), "1000 Mbps")

    def test_bytes_mode(self) -> None:
        self.assertEqual(format_speed(1_000_000, use_bytes=True), "1.0 MB/s")
        self.assertEqual(format_rate(1_500), "2 KB/s")
        self.assertEqual(format_rate(500), "500 B/s")
        self.assertEqual(format_rate(2_500_000), "2.5 MB/s")


class AverageTest(unittest.TestCase):
    def test_skips_ramp_up(self) -> None:
        events = [(0.0, 0.0), (0.3, 300.0), (0.8, 800.0), (2.0, 2000.0)]
        self.assertAlmostEqual(average(events), (2000.0 - 300.0) / 1.6)

    def test_small_samples_return_zero(self) -> None:
        self.assertEqual(average([]), 0.0)
        self.assertEqual(average([(0.05, 100.0)]), 0.0)
        self.assertEqual(average([(0.2, 0.0)]), 0.0)

    def test_short_test_does_not_skip(self) -> None:
        self.assertAlmostEqual(average([(0.0, 0.0), (0.5, 100.0), (1.0, 300.0)]), 300.0)


class ModelTest(unittest.TestCase):
    def test_result_round_trip(self) -> None:
        result = SpeedResult("2026-10-22T12:30:00+00:00", 42.5, 8.25, 23, id="fixed")
        copy = SpeedResult.from_dict(result.to_dict())
        self.assertEqual(copy.to_dict(), result.to_dict())
        self.assertEqual(copy.when.year, 2026)

    def test_bad_values_fall_back(self) -> None:
        result = SpeedResult.from_dict({"down": None, "up": "x", "ping": None})
        self.assertEqual((result.down, result.up, result.ping), (0.0, 0.0, 0))

    def test_meta(self) -> None:
        meta = SpeedMeta.from_dict(
            {
                "clientIp": "203.0.113.1",
                "asOrganization": "Example ISP",
                "country": "IR",
                "httpProtocol": "HTTP/2",
                "colo": {"iata": "FRA", "city": "Frankfurt"},
            }
        )
        self.assertEqual(meta.client_ip, "203.0.113.1")
        self.assertEqual(meta.organization, "Example ISP")
        self.assertEqual(meta.colo, "FRA")
        self.assertEqual(meta.city, "Frankfurt")
        self.assertEqual(meta.protocol, "HTTP/2")


if __name__ == "__main__":
    unittest.main()
