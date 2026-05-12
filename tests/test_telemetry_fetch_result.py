import unittest

import requests

from bomana.core.telemetry import Budget, HttpJson, MapObjectsFetcher, TelemetryFetcher


class FakeResponse:
    def __init__(self, *, ok=True, status_code=200, payload=None, json_exc=None):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class HttpJsonFetchResultTests(unittest.TestCase):
    def test_success_returns_payload_and_endpoint(self) -> None:
        http = HttpJson(FakeSession(FakeResponse(payload={"valid": True})))

        result = http.get_json("http://127.0.0.1:8111/indicators", Budget(1.0))

        self.assertTrue(result.ok)
        self.assertEqual(result.endpoint, "/indicators")
        self.assertEqual(result.payload, {"valid": True})
        self.assertEqual(result.error_kind, "")
        self.assertGreaterEqual(result.elapsed_ms, 0.0)

    def test_budget_exhausted_is_classified_without_request(self) -> None:
        session = FakeSession(FakeResponse(payload={}))
        http = HttpJson(session)

        result = http.get_json("http://127.0.0.1:8111/state", Budget(0.0))

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "budget_exhausted")
        self.assertEqual(session.calls, [])

    def test_timeout_is_classified(self) -> None:
        http = HttpJson(FakeSession(requests.Timeout("slow")))

        result = http.get_json("http://127.0.0.1:8111/state", Budget(1.0))

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "timeout")

    def test_status_failure_is_classified(self) -> None:
        http = HttpJson(FakeSession(FakeResponse(ok=False, status_code=503)))

        result = http.get_json("http://127.0.0.1:8111/map_obj.json", Budget(1.0))

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "status")
        self.assertEqual(result.status_code, 503)

    def test_invalid_json_is_classified(self) -> None:
        http = HttpJson(FakeSession(FakeResponse(json_exc=ValueError("bad json"))))

        result = http.get_json("http://127.0.0.1:8111/map_info.json", Budget(1.0))

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "invalid_json")


class FetcherDiagnosticTests(unittest.TestCase):
    def test_telemetry_fetcher_preserves_tolerant_booleans(self) -> None:
        http = HttpJson(FakeSession(requests.Timeout("slow")))

        data = TelemetryFetcher(http).fetch(Budget(1.0))

        self.assertFalse(data.ind_ok)
        self.assertFalse(data.state_resp_ok)
        self.assertEqual(data.ind_error_kind, "timeout")

    def test_map_fetcher_attaches_failure_diagnostics(self) -> None:
        http = HttpJson(FakeSession(FakeResponse(ok=False, status_code=500)))

        data = MapObjectsFetcher(http).fetch(Budget(1.0))

        self.assertFalse(data.ok)
        self.assertEqual(data.error_kind, "status")
        self.assertGreaterEqual(data.elapsed_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
