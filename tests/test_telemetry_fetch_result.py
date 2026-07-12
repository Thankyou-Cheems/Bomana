import unittest

import requests

from bomana.core.telemetry import (
    Budget,
    HttpJson,
    MapIconFontFetcher,
    MapImageFetcher,
    MapObjectsFetcher,
    TelemetryFetcher,
)


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


class FakeRouteSession:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        for endpoint, result in self.results.items():
            if url.endswith(endpoint):
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"Unexpected URL: {url}")


class FakeImageResponse:
    def __init__(self, body_chunks, *, content_type="image/png", content_length=None):
        self.ok = True
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.body_chunks = body_chunks
        self.closed = False

    def iter_content(self, *, chunk_size):
        assert chunk_size > 0
        yield from self.body_chunks

    def close(self):
        self.closed = True


class FakeImageSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, *, timeout, stream):
        self.calls.append((url, timeout, stream))
        return self.response


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

    def test_tiny_positive_budget_is_classified_without_request(self) -> None:
        session = FakeSession(FakeResponse(payload={}))
        http = HttpJson(session)

        result = http.get_json("http://127.0.0.1:8111/state", Budget(0.001))

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


class MapImageFetcherTests(unittest.TestCase):
    def test_accepts_bounded_png_from_fixed_official_route(self) -> None:
        body = b"\x89PNG\r\n\x1a\nmap"
        response = FakeImageResponse([body], content_length=len(body))
        session = FakeImageSession(response)

        result = MapImageFetcher(session).fetch()

        self.assertTrue(result.ok)
        self.assertEqual(result.body, body)
        self.assertEqual(result.content_type, "image/png")
        self.assertTrue(session.calls[0][0].endswith("/map.img"))
        self.assertTrue(session.calls[0][2])
        self.assertTrue(response.closed)

    def test_rejects_wrong_type_signature_and_declared_oversize(self) -> None:
        cases = (
            (FakeImageResponse([b"bad"], content_type="text/html"), "invalid_content_type"),
            (FakeImageResponse([b"not-png"]), "invalid_image"),
            (
                FakeImageResponse(
                    [b"\x89PNG\r\n\x1a\n"],
                    content_length=MapImageFetcher.MAX_IMAGE_BYTES + 1,
                ),
                "body_too_large",
            ),
        )
        for response, reason in cases:
            with self.subTest(reason=reason):
                result = MapImageFetcher(FakeImageSession(response)).fetch()
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, reason)
                self.assertTrue(response.closed)

    def test_rejects_stream_that_crosses_hard_body_limit(self) -> None:
        response = FakeImageResponse(
            [b"\x89PNG\r\n\x1a\n" + b"a" * MapImageFetcher.MAX_IMAGE_BYTES, b"b"]
        )

        result = MapImageFetcher(FakeImageSession(response)).fetch()

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "body_too_large")


class MapIconFontFetcherTests(unittest.TestCase):
    def test_accepts_bounded_truetype_font_from_fixed_official_route(self) -> None:
        body = b"\x00\x01\x00\x00" + b"official-font"
        response = FakeImageResponse([body], content_type="text/plain", content_length=len(body))
        session = FakeImageSession(response)

        result = MapIconFontFetcher(session).fetch()

        self.assertTrue(result.ok)
        self.assertEqual(result.body, body)
        self.assertTrue(session.calls[0][0].endswith("/icons.ttf"))
        self.assertTrue(response.closed)

    def test_rejects_invalid_signature_and_oversize_font(self) -> None:
        cases = (
            (FakeImageResponse([b"not-font"], content_type="text/plain"), "invalid_font"),
            (
                FakeImageResponse(
                    [b"\x00\x01\x00\x00"],
                    content_type="text/plain",
                    content_length=MapIconFontFetcher.MAX_FONT_BYTES + 1,
                ),
                "body_too_large",
            ),
        )
        for response, reason in cases:
            with self.subTest(reason=reason):
                result = MapIconFontFetcher(FakeImageSession(response)).fetch()
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, reason)
                self.assertTrue(response.closed)


class FetcherDiagnosticTests(unittest.TestCase):
    def test_telemetry_fetcher_preserves_tolerant_booleans(self) -> None:
        http = HttpJson(FakeSession(requests.Timeout("slow")))

        data = TelemetryFetcher(http).fetch(Budget(1.0))

        self.assertFalse(data.ind_ok)
        self.assertFalse(data.state_resp_ok)
        self.assertEqual(data.ind_error_kind, "timeout")

    def test_telemetry_fetcher_reads_state_after_indicators_failure(self) -> None:
        session = FakeRouteSession(
            {
                "/indicators": FakeResponse(ok=False, status_code=503),
                "/state": FakeResponse(
                    payload={
                        "IAS, km/h": 420,
                        "Vy, m/s": -4.5,
                        "Mfuel, kg": 1500,
                        "Mfuel0, kg": 2200,
                        "H, m": 3200,
                        "TAS, km/h": 510,
                        "throttle 1, %": 86,
                        "M": 0.62,
                        "gear, %": 0,
                    }
                ),
            }
        )
        http = HttpJson(session)

        data = TelemetryFetcher(http).fetch(Budget(1.0))

        self.assertFalse(data.ind_ok)
        self.assertEqual(data.ind_error_kind, "status")
        self.assertTrue(data.state_resp_ok)
        self.assertEqual(data.state_error_kind, "")
        self.assertGreaterEqual(data.state_elapsed_ms, 0.0)
        self.assertEqual(data.ias_kmh, 420)
        self.assertEqual(data.vy_ms, -4.5)
        self.assertEqual(data.fuel_kg, 1500)
        self.assertEqual(data.fuel0_kg, 2200)
        self.assertEqual(data.altitude_m, 3200)
        self.assertEqual(data.tas_kmh, 510)
        self.assertEqual(data.throttle_pct, 86)
        self.assertEqual(data.mach, 0.62)
        self.assertFalse(data.gear_down)
        self.assertFalse(data.valid)
        self.assertFalse(data.entity_like)
        self.assertEqual(
            [url.removeprefix("http://127.0.0.1:8111") for url, _timeout in session.calls],
            ["/indicators", "/state"],
        )

    def test_telemetry_fetcher_rejects_empty_state_payload(self) -> None:
        session = FakeRouteSession(
            {
                "/indicators": FakeResponse(payload={"valid": True, "type": "test_plane"}),
                "/state": FakeResponse(payload={}),
            }
        )
        http = HttpJson(session)

        data = TelemetryFetcher(http).fetch(Budget(1.0))

        self.assertTrue(data.ind_ok)
        self.assertFalse(data.state_resp_ok)
        self.assertEqual(data.state_error_kind, "schema")
        self.assertEqual(data.ias_kmh, 0)
        self.assertEqual(data.altitude_m, 0)
        self.assertFalse(data.entity_like)

    def test_telemetry_fetcher_rejects_state_missing_required_fields(self) -> None:
        session = FakeRouteSession(
            {
                "/indicators": FakeResponse(payload={"valid": True, "type": "test_plane"}),
                "/state": FakeResponse(
                    payload={
                        "IAS, km/h": 420,
                        "Vy, m/s": -4.5,
                        "Mfuel, kg": 1500,
                    }
                ),
            }
        )
        http = HttpJson(session)

        data = TelemetryFetcher(http).fetch(Budget(1.0))

        self.assertFalse(data.state_resp_ok)
        self.assertEqual(data.state_error_kind, "schema")
        self.assertEqual(data.ias_kmh, 0)
        self.assertEqual(data.vy_ms, 0)
        self.assertEqual(data.fuel_kg, 0)

    def test_telemetry_fetcher_rejects_non_finite_state_numbers(self) -> None:
        session = FakeRouteSession(
            {
                "/indicators": FakeResponse(
                    payload={
                        "valid": True,
                        "type": "test_plane",
                        "compass": "Infinity",
                        "wing_sweep_indicator": "nan",
                    }
                ),
                "/state": FakeResponse(
                    payload={
                        "IAS, km/h": 420,
                        "Vy, m/s": -4.5,
                        "Mfuel, kg": 1500,
                        "Mfuel0, kg": "-Infinity",
                        "H, m": 3200,
                        "TAS, km/h": "Infinity",
                        "throttle 1, %": "nan",
                        "M": "Infinity",
                        "gear, %": "nan",
                        "aviahorizon_pitch": "nan",
                        "aviahorizon_roll": "Infinity",
                    }
                ),
            }
        )
        http = HttpJson(session)

        data = TelemetryFetcher(http).fetch(Budget(1.0))

        self.assertTrue(data.state_resp_ok)
        self.assertFalse(data.compass_present)
        self.assertIsNone(data.wing_sweep)
        self.assertEqual(data.ias_kmh, 420)
        self.assertEqual(data.vy_ms, -4.5)
        self.assertEqual(data.fuel_kg, 1500)
        self.assertEqual(data.altitude_m, 3200)
        self.assertEqual(data.fuel0_kg, 0)
        self.assertEqual(data.tas_kmh, 0)
        self.assertEqual(data.throttle_pct, 0)
        self.assertIsNone(data.mach)
        self.assertEqual(data.gear_pct, 0)
        self.assertFalse(data.gear_down)
        self.assertFalse(data.attitude_pitch_present)
        self.assertFalse(data.attitude_roll_present)
        self.assertFalse(data.attitude_available)

        self.assertEqual(TelemetryFetcher._to_float({"value": "nan"}, 12.5), 12.5)
        self.assertIsNone(TelemetryFetcher._to_optional_float(["Infinity"]))

    def test_map_fetcher_attaches_failure_diagnostics(self) -> None:
        http = HttpJson(FakeSession(FakeResponse(ok=False, status_code=500)))

        data = MapObjectsFetcher(http).fetch(Budget(1.0))

        self.assertFalse(data.ok)
        self.assertEqual(data.error_kind, "status")
        self.assertGreaterEqual(data.elapsed_ms, 0.0)

    def test_map_fetcher_rejects_malformed_payload_shape(self) -> None:
        for payload in ("bad-shape", {"unexpected": []}):
            with self.subTest(payload=payload):
                http = HttpJson(FakeSession(FakeResponse(payload=payload)))

                data = MapObjectsFetcher(http).fetch(Budget(1.0))

                self.assertFalse(data.ok)
                self.assertEqual(data.error_kind, "schema")
                self.assertEqual(data.obj_count, 0)

    def test_map_fetcher_accepts_legitimate_empty_object_lists(self) -> None:
        for payload in ([], {"objects": []}):
            with self.subTest(payload=payload):
                http = HttpJson(FakeSession(FakeResponse(payload=payload)))

                data = MapObjectsFetcher(http).fetch(Budget(1.0))

                self.assertTrue(data.ok)
                self.assertEqual(data.error_kind, "")
                self.assertEqual(data.obj_count, 0)


if __name__ == "__main__":
    unittest.main()
