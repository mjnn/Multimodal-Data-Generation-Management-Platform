"""Tests for enum_tree depth crop and LABEL_TREE_OUTPUT modes."""
from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

from oms_multimodal.label_prompt import build_taxonomy_prompt_block
from oms_multimodal.taxonomy import normalize_model_labels, taxonomy_prompt_block
from oms_multimodal.taxonomy_tree import (
    LabelingTaxonomyOptions,
    crop_taxonomy,
    format_enum_tree_for_prompt,
    normalize_tree_value,
    parse_depth_by_dim,
    resolve_label_depth,
    resolve_labeling_taxonomy_options,
)


WEATHER_SCHEMA = {
    "type": "enum_tree",
    "values": [
        {"id": "sunny"},
        {"id": "cloudy"},
        {
            "id": "rain",
            "children": [
                {"id": "light_rain"},
                {"id": "moderate_rain"},
                {"id": "heavy_rain"},
            ],
        },
    ],
    "labels": {
        "sunny": "晴",
        "cloudy": "多云",
        "rain": "雨",
        "light_rain": "小雨",
        "moderate_rain": "中雨",
        "heavy_rain": "大雨",
    },
}

SAMPLE_TAXONOMY = {
    "version": "test",
    "labels": [
        {
            "id": "L1.3.weather",
            "name": "天气",
            "level_code": "L1.3",
            "level_name": "天气",
            "value_schema": deepcopy(WEATHER_SCHEMA),
        },
        {
            "id": "L1.1.day_period",
            "name": "日时段",
            "level_code": "L1.1",
            "level_name": "时间维度",
            "value_schema": {
                "type": "enum",
                "values": ["morning", "noon", "night"],
                "labels": {"morning": "上午", "noon": "中午", "night": "夜晚"},
            },
        },
    ],
}


class TestDepthParse(unittest.TestCase):
    def test_parse_csv_and_json(self) -> None:
        self.assertEqual(parse_depth_by_dim("L1.3=2,L1.1=1"), {"L1.3": 2, "L1.1": 1})
        self.assertEqual(parse_depth_by_dim('{"L1.3": 3}'), {"L1.3": 3})

    def test_resolve_dim_override(self) -> None:
        self.assertEqual(
            resolve_label_depth("L1.3", global_depth=1, depth_by_dim={"L1.3": 2}),
            2,
        )
        self.assertEqual(
            resolve_label_depth("L1.1", global_depth=1, depth_by_dim={"L1.3": 2}),
            1,
        )


class TestCrop(unittest.TestCase):
    def test_global_depth_1_drops_rain_children(self) -> None:
        cropped = crop_taxonomy(
            SAMPLE_TAXONOMY,
            options=LabelingTaxonomyOptions(depth=1, output_mode="path"),
        )
        weather = next(x for x in cropped["labels"] if x["id"] == "L1.3.weather")
        rain = next(n for n in weather["value_schema"]["values"] if n["id"] == "rain")
        self.assertNotIn("children", rain)

    def test_dim_override_keeps_depth_2(self) -> None:
        cropped = crop_taxonomy(
            SAMPLE_TAXONOMY,
            options=LabelingTaxonomyOptions(
                depth=1,
                depth_by_dim={"L1.3": 2},
                output_mode="path",
            ),
        )
        weather = next(x for x in cropped["labels"] if x["id"] == "L1.3.weather")
        rain = next(n for n in weather["value_schema"]["values"] if n["id"] == "rain")
        self.assertEqual(
            [c["id"] for c in rain["children"]],
            ["light_rain", "moderate_rain", "heavy_rain"],
        )

    def test_flat_enum_unchanged(self) -> None:
        cropped = crop_taxonomy(
            SAMPLE_TAXONOMY,
            options=LabelingTaxonomyOptions(depth=1),
        )
        day = next(x for x in cropped["labels"] if x["id"] == "L1.1.day_period")
        self.assertEqual(day["value_schema"]["type"], "enum")
        self.assertEqual(day["value_schema"]["values"], ["morning", "noon", "night"])


class TestNormalizeOutputModes(unittest.TestCase):
    def test_leaf_path_ancestors(self) -> None:
        leaf = normalize_tree_value(WEATHER_SCHEMA, "heavy_rain", output_mode="leaf")
        self.assertEqual(leaf, "heavy_rain")
        path = normalize_tree_value(WEATHER_SCHEMA, ["rain", "heavy_rain"], output_mode="path")
        self.assertEqual(path, ["rain", "heavy_rain"])
        anc = normalize_tree_value(WEATHER_SCHEMA, "大雨", output_mode="ancestors")
        self.assertEqual(anc["leaf"], "heavy_rain")
        self.assertEqual(anc["path"], ["rain", "heavy_rain"])
        self.assertEqual(anc["levels"], {"1": "rain", "2": "heavy_rain"})

    def test_invalid_dropped_in_normalize_model_labels(self) -> None:
        out = normalize_model_labels(
            SAMPLE_TAXONOMY,
            {
                "L1.3.weather": {"value": "typhoon", "confidence": 0.9},
                "L1.1.day_period": {"value": "morning", "confidence": 0.8},
            },
            options=LabelingTaxonomyOptions(depth=0, output_mode="path"),
        )
        self.assertNotIn("L1.3.weather", out)
        self.assertIn("L1.1.day_period", out)

    def test_env_output_mode(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LABEL_TAXONOMY_DEPTH": "0",
                "LABEL_TREE_OUTPUT": "leaf",
                "LABEL_TAXONOMY_DEPTH_BY_DIM": "",
            },
            clear=False,
        ):
            opts = resolve_labeling_taxonomy_options()
            self.assertEqual(opts.output_mode, "leaf")
            out = normalize_model_labels(
                SAMPLE_TAXONOMY,
                {"L1.3.weather": {"value": ["rain", "light_rain"]}},
            )
            self.assertEqual(out["L1.3.weather"]["value"], "light_rain")


class TestPrompt(unittest.TestCase):
    def test_prompt_contains_nested_tree(self) -> None:
        text = taxonomy_prompt_block(
            SAMPLE_TAXONOMY,
            None,
            options=LabelingTaxonomyOptions(depth=0, output_mode="path"),
        )
        self.assertIn("enum_tree", text)
        self.assertIn("heavy_rain", text)
        self.assertIn("路径数组", text)

    def test_scaffold_builders(self) -> None:
        from oms_multimodal.taxonomy_tree import (
            enum_tree_node,
            make_enum_tree_schema,
            minimal_enum_tree_example,
            tree_depth,
            validate_enum_tree_schema,
            crop_value_schema,
        )

        sample = minimal_enum_tree_example()
        self.assertEqual(validate_enum_tree_schema(sample), [])
        self.assertEqual(tree_depth(sample), 2)
        schema = make_enum_tree_schema(
            enum_tree_node("x", enum_tree_node("x1")),
            enum_tree_node("y"),
        )
        cropped = crop_value_schema(schema, 1)
        assert cropped is not None
        x = next(n for n in cropped["values"] if n["id"] == "x")
        self.assertNotIn("children", x)
        bad = make_enum_tree_schema(enum_tree_node("dup"), enum_tree_node("dup"))
        self.assertTrue(any("duplicate" in e for e in validate_enum_tree_schema(bad)))

    def test_format_tree(self) -> None:
        s = format_enum_tree_for_prompt(WEATHER_SCHEMA)
        self.assertIn("rain", s)
        self.assertIn("heavy_rain", s)

    def test_weather_minimal_sample_optional(self) -> None:
        """Bundled may keep one weather enum_tree sample; not required for scaffold."""
        from oms_multimodal import bundled_taxonomy_path, load_taxonomy

        tax = load_taxonomy(bundled_taxonomy_path())
        by_id = {x["id"]: x for x in tax["labels"]}
        weather = by_id["L1.3.weather"]["value_schema"]
        self.assertIn(weather.get("type"), {"enum", "enum_tree"})

    def test_build_prompt_direct(self) -> None:
        block = build_taxonomy_prompt_block(SAMPLE_TAXONOMY, None, tree_output_mode="ancestors")
        self.assertIn('"levels"', block)
        self.assertIn("leaf", block)


if __name__ == "__main__":
    unittest.main()
