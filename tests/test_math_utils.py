import math
import unittest

from bomana.utils.math_utils import calculate_relative_bearing, normalize_angle


class MathUtilsTests(unittest.TestCase):
    def test_normalize_angle_handles_non_finite_values(self) -> None:
        self.assertEqual(normalize_angle(float("inf")), 0.0)
        self.assertEqual(normalize_angle(float("-inf")), 0.0)
        self.assertEqual(normalize_angle(float("nan")), 0.0)

    def test_normalize_angle_preserves_boundary_behavior(self) -> None:
        self.assertEqual(normalize_angle(180.0), 180.0)
        self.assertEqual(normalize_angle(-180.0), -180.0)
        self.assertEqual(normalize_angle(540.0), 180.0)
        self.assertEqual(normalize_angle(-540.0), -180.0)
        self.assertEqual(normalize_angle(725.0), 5.0)

    def test_relative_bearing_uses_safe_normalization(self) -> None:
        self.assertEqual(calculate_relative_bearing(float("inf"), 90.0), 0.0)
        self.assertTrue(math.isfinite(calculate_relative_bearing(10_000_000.0, 90.0)))


if __name__ == "__main__":
    unittest.main()
