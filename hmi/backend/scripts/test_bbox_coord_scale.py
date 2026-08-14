"""Unit tests for native↔preview canvas bbox mapping."""

from __future__ import annotations

import unittest


class TestLongEdgeFitParity(unittest.TestCase):
    def test_640x360_to_1920x1080_scales_3x(self) -> None:
        # Mirror frontend utils/bboxCoords.ts computeLongEdgeFit
        iw, ih = 640, 360
        cw, ch = 1920, 1080
        src_long = max(iw, ih)
        tgt_long = max(cw, ch)
        scale = tgt_long / float(src_long)
        self.assertAlmostEqual(scale, 3.0)
        x_native = 443.0
        y_native = 100.0
        x_canvas = x_native * scale  # no pad for this AR
        y_canvas = y_native * scale
        self.assertAlmostEqual(x_canvas, 1329.0)
        self.assertAlmostEqual(y_canvas, 300.0)


if __name__ == "__main__":
    unittest.main()
