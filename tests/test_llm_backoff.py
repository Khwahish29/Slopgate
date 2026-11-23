"""Rate-limit and transient-error handling in OpenAICompatClient. No network, no real sleeping."""
import io
import json
import os
import random
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from slopgate.agent_layer import agent                                           # noqa: E402
from slopgate.agent_layer import llm                                             # noqa: E402
from slopgate.agent_layer.llm import ModelError, OpenAICompatClient, RateLimitError  # noqa: E402

MSG = [{"role": "user", "content": "q"}]


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ok(text="hi", tokens=5):
    return Resp(json.dumps({"choices": [{"message": {"content": text}}], "usage": {"total_tokens": tokens}}).encode())


def http(code, headers=None, body=b""):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body))


def client(**kw):
    sleeps = []
    c = OpenAICompatClient("http://x", "k", "m", sleep=sleeps.append, rng=random.Random(3), **kw)
    return c, sleeps


class Parsing(unittest.TestCase):
    def test_retry_after_header(self):
        self.assertEqual(llm.parse_retry_after("12"), 12.0)
        self.assertEqual(llm.parse_retry_after("0.5"), 0.5)
        self.assertEqual(llm.parse_retry_after("-4"), 0.0)
        self.assertIsNone(llm.parse_retry_after(None))
        self.assertIsNone(llm.parse_retry_after("soon"))

    def test_retry_after_http_date_in_the_past_is_zero(self):
        self.assertEqual(llm.parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT"), 0.0)

    def test_hint_in_error_body(self):
        self.assertEqual(llm.retry_hint_from_body("Rate limit reached. Please try again in 7.2s."), 7.2)
        self.assertEqual(llm.retry_hint_from_body("try again in 820ms"), 0.82)
        self.assertEqual(llm.retry_hint_from_body("try again in 1m3.5s"), 63.5)
        self.assertIsNone(llm.retry_hint_from_body("internal error"))
        self.assertIsNone(llm.retry_hint_from_body(""))

    def test_backoff_grows_stays_in_jitter_band_and_is_capped(self):
        rng = random.Random(0)
        for attempt in range(5):
            lo, hi = 2.0 * 2 ** attempt * 0.75, 2.0 * 2 ** attempt * 1.25
            for _ in range(50):
                self.assertTrue(lo <= llm.backoff_delay(attempt, rng=rng) <= min(hi, llm.BACKOFF_CAP_S))
        self.assertEqual(llm.backoff_delay(20, rng=rng), llm.BACKOFF_CAP_S)

    def test_server_wait_is_a_floor_not_a_suggestion(self):
        rng = random.Random(0)
        for _ in range(50):
            self.assertGreaterEqual(llm.backoff_delay(0, server_wait=9.0, rng=rng), 9.0)
        self.assertEqual(llm.backoff_delay(0, server_wait=500, rng=rng), llm.BACKOFF_CAP_S)


class Retries(unittest.TestCase):
    def test_429_then_success_honours_retry_after(self):
        c, sleeps = client()
        with mock.patch.object(urllib.request, "urlopen", side_effect=[http(429, {"Retry-After": "7"}), ok()]):
            self.assertEqual(c.chat(MSG), "hi")
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 7.0)
        self.assertEqual((c.retries, c.rate_limited, c.calls), (1, 1, 1))
        self.assertAlmostEqual(c.wait_s, sleeps[0])

    def test_hint_in_body_is_used_when_no_header(self):
        c, sleeps = client()
        body = b'{"error":{"message":"Rate limit reached. Please try again in 3.5s."}}'
        with mock.patch.object(urllib.request, "urlopen", side_effect=[http(429, {}, body), ok()]):
            c.chat(MSG)
        self.assertGreaterEqual(sleeps[0], 3.5)

    def test_without_any_hint_backoff_doubles(self):
        c, sleeps = client()
        with mock.patch.object(urllib.request, "urlopen", side_effect=[http(503), http(503), http(503), ok()]):
            c.chat(MSG)
        self.assertEqual(len(sleeps), 3)
        self.assertTrue(sleeps[0] < sleeps[1] < sleeps[2])
        self.assertEqual(c.rate_limited, 0)            # 503 is a retry, not a rate limit

    def test_exhausted_429_raises_a_rate_limit_error_the_agent_recognises(self):
        c, sleeps = client(max_retries=2)
        with mock.patch.object(urllib.request, "urlopen", side_effect=[http(429, {"Retry-After": "4"})] * 3):
            with self.assertRaises(RateLimitError) as cm:
                c.chat(MSG)
        e = cm.exception
        self.assertIsInstance(e, ModelError)             # older handlers still catch it
        self.assertEqual(e.retry_after, 4.0)
        self.assertTrue(agent.is_rate_limit(e))          # agent.ThrottledClient keys on this
        self.assertEqual(agent.retry_after_s(e), 4.0)
        self.assertEqual((len(sleeps), c.calls), (2, 0))  # two retries, no success counted

    def test_client_errors_are_not_retried(self):
        for code in (400, 401, 403, 404):
            c, sleeps = client()
            with mock.patch.object(urllib.request, "urlopen", side_effect=[http(code)]):
                with self.assertRaises(ModelError) as cm:
                    c.chat(MSG)
            self.assertNotIsInstance(cm.exception, RateLimitError)
            self.assertEqual((sleeps, c.retries), ([], 0))

    def test_transient_network_error_is_retried(self):
        c, sleeps = client()
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=[urllib.error.URLError("connection reset"), TimeoutError("slow"), ok()]):
            self.assertEqual(c.chat(MSG), "hi")
        self.assertEqual(c.retries, 2)

    def test_max_retries_zero_fails_fast(self):
        c, sleeps = client(max_retries=0)
        with mock.patch.object(urllib.request, "urlopen", side_effect=[http(429)]):
            with self.assertRaises(RateLimitError):
                c.chat(MSG)
        self.assertEqual(sleeps, [])

    def test_env_sets_default_retries(self):
        with mock.patch.dict(os.environ, {"SLOPGATE_MAX_RETRIES": "1"}):
            self.assertEqual(OpenAICompatClient("http://x", "k", "m").max_retries, 1)
        with mock.patch.dict(os.environ, {"SLOPGATE_MAX_RETRIES": "-3"}):
            self.assertEqual(OpenAICompatClient("http://x", "k", "m").max_retries, 0)


class Cache(unittest.TestCase):
    def test_failures_are_not_cached_and_successes_are(self):
        d = tempfile.mkdtemp()
        c, _ = client(max_retries=0)
        c.cache_dir = d
        with mock.patch.object(urllib.request, "urlopen", side_effect=[http(429)]):
            with self.assertRaises(RateLimitError):
                c.chat(MSG)
        self.assertEqual(os.listdir(d), [])
        with mock.patch.object(urllib.request, "urlopen", side_effect=[ok("first")]) as m:
            self.assertEqual(c.chat(MSG), "first")
        with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("must not call")):
            self.assertEqual(c.chat(MSG), "first")
        self.assertEqual((c.calls, c.cache_hits), (1, 1))

    def test_call_cap_still_applies_and_is_not_retried(self):
        c, sleeps = client()
        c.max_calls = 0
        with self.assertRaises(ModelError):
            c.chat(MSG)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
