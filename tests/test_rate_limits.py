import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rate_limits import AppServerClient, Unavailable, select_weekly


NOW = 1_790_000_000


def window(minutes, used=23.5, reset=NOW + 60_000):
    return {"windowDurationMins": minutes, "usedPercent": used, "resetsAt": reset}


def result(primary=None, secondary=None):
    return {"rateLimitsByLimitId": {"codex": {"limitId": "codex", "primary": primary, "secondary": secondary}}}


class SelectionTests(unittest.TestCase):
    def test_week_in_primary_is_selected_by_duration(self):
        quota = select_weekly(result(window(10080), window(300, 99)), now=NOW)
        self.assertEqual(quota.remaining_percent, 76.5)
        self.assertEqual(quota.window_name, "primary")

    def test_week_in_secondary_is_selected_by_duration(self):
        quota = select_weekly(result(window(300, 99), window(10080)), now=NOW)
        self.assertEqual(quota.remaining_percent, 76.5)
        self.assertEqual(quota.window_name, "secondary")

    def test_legacy_response(self):
        quota = select_weekly({"rateLimits": {"secondary": window(10080)}}, now=NOW)
        self.assertEqual(quota.remaining_percent, 76.5)

    def test_multi_bucket_wins_over_legacy_and_other_limits(self):
        data = result(window(10080, 80))
        data["rateLimits"] = {"primary": window(10080, 10)}
        data["rateLimitsByLimitId"]["codex_other"] = {"primary": window(10080, 1)}
        self.assertEqual(select_weekly(data, now=NOW).remaining_percent, 20)

    def test_wrong_or_ambiguous_windows_are_rejected(self):
        bad_results = [None, {}, {"rateLimitsByLimitId": {}}, result(window(300)),
                       result(window(None)), result(window("10080")),
                       result(window(10080), window(10080))]
        for data in bad_results:
            with self.subTest(data=data), self.assertRaises(Unavailable):
                select_weekly(data, now=NOW)

    def test_wrong_bucket_is_rejected(self):
        with self.assertRaises(Unavailable):
            select_weekly({"rateLimits": {"limitId": "other", "primary": window(10080)}}, now=NOW)

    def test_invalid_usage_is_rejected(self):
        for used in [None, True, "25", -1, float("nan"), float("inf")]:
            with self.subTest(used=used), self.assertRaises(Unavailable):
                select_weekly(result(window(10080, used)), now=NOW)

    def test_reset_must_be_valid_future_unix_seconds(self):
        for reset in [None, True, "1791000000", NOW, NOW - 1, NOW + 0.1, 10**40]:
            with self.subTest(reset=reset), self.assertRaises(Unavailable):
                select_weekly(result(window(10080, reset=reset)), now=NOW)

    def test_zero_full_and_over_limit_values(self):
        for used, remaining in [(0, 100), (100, 0), (102, 0), (99.9, 0.1)]:
            with self.subTest(used=used):
                self.assertAlmostEqual(select_weekly(result(window(10080, used)), now=NOW).remaining_percent, remaining)


class CaptureInput(io.StringIO):
    def close(self):
        self.captured = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, messages):
        self.stdin = CaptureInput()
        self.stdout = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
        self.killed = False
        self.waited = False

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def kill(self):
        self.killed = True


class ProtocolTests(unittest.TestCase):
    def test_only_initialize_and_rate_limits_are_requested(self):
        data = result(window(10080, reset=2_000_000_000))
        process = FakeProcess([{"id": 1, "result": {}}, {"id": 2, "result": data}])
        with patch("rate_limits.find_codex", return_value="codex.exe"), patch("rate_limits.subprocess.Popen", return_value=process) as start:
            quota = AppServerClient().read()
        sent = [json.loads(line) for line in process.stdin.captured.splitlines()]
        self.assertEqual([message["method"] for message in sent], ["initialize", "initialized", "account/rateLimits/read"])
        self.assertEqual(start.call_args.args[0], ["codex.exe", "app-server", "--listen", "stdio://"])
        self.assertEqual(quota.remaining_percent, 76.5)
        self.assertTrue(process.waited)
        self.assertTrue(process.stdout.closed)

    def test_raw_rpc_error_is_never_exposed(self):
        process = FakeProcess([{"id": 1, "result": {}}, {"id": 2, "error": {"code": -32000, "message": "PRIVATE_SENTINEL"}}])
        with patch("rate_limits.find_codex", return_value="codex.exe"), patch("rate_limits.subprocess.Popen", return_value=process):
            with self.assertRaises(Unavailable) as failure:
                AppServerClient().read()
        self.assertNotIn("PRIVATE_SENTINEL", str(failure.exception))

    def test_unsupported_method_has_safe_message(self):
        process = FakeProcess([{"id": 1, "result": {}}, {"id": 2, "error": {"code": -32601}}])
        with patch("rate_limits.find_codex", return_value="codex.exe"), patch("rate_limits.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(Unavailable, "不支持额度接口"):
                AppServerClient().read()

    def test_exit_and_timeout_return_unavailable(self):
        process = FakeProcess([])
        with patch("rate_limits.find_codex", return_value="codex.exe"), patch("rate_limits.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(Unavailable, "已退出"):
                AppServerClient().read()

        release = threading.Event()

        class QuietStream:
            def __iter__(self):
                release.wait(timeout=2)
                return iter(())

            def close(self):
                release.set()

        process = FakeProcess([])
        process.stdout = QuietStream()
        with patch("rate_limits.find_codex", return_value="codex.exe"), patch("rate_limits.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(Unavailable, "超时"):
                AppServerClient(timeout=0.03).read()

    def test_cancel_kills_owned_process(self):
        process = FakeProcess([])
        client = AppServerClient()
        client._process = process
        client.cancel()
        self.assertTrue(process.killed)
        with self.assertRaisesRegex(Unavailable, "取消"):
            client.read()


if __name__ == "__main__":
    unittest.main()
