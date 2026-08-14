"""Smoke tests: overview clip query label filters + scene text relevance."""

from __future__ import annotations

import json
import unittest

import numpy as np

from hmi.labels_util import match_label_filters
from hmi.services.clip_query_common import (
    DEFAULT_MIN_EMBED_SCORE,
    DEFAULT_MIN_TEXT_SCORE,
    apply_semantic_rank_cutoff,
    normalize_label_filters,
    score_clip_candidate,
    text_relevance_score,
)


class MatchLabelFiltersExtendedTests(unittest.TestCase):
    def test_equality_and_bool(self) -> None:
        labels = {"day_period": "night", "has_child": True}
        self.assertTrue(match_label_filters(labels, {"day_period": "night"}))
        self.assertFalse(match_label_filters(labels, {"day_period": "day"}))
        self.assertTrue(match_label_filters(labels, {"has_child": True}))
        self.assertFalse(match_label_filters(labels, {"has_child": False}))

    def test_multi_value_or(self) -> None:
        labels = {"seat": "rear_left"}
        self.assertTrue(match_label_filters(labels, {"seat": ["rear_left", "rear_right"]}))
        self.assertFalse(match_label_filters(labels, {"seat": ["front_left"]}))
        self.assertTrue(match_label_filters(labels, {"seat": {"in": ["rear_left"]}}))

    def test_numeric_range(self) -> None:
        labels = {"passenger_count": "3"}
        self.assertTrue(match_label_filters(labels, {"passenger_count": {"min": 2, "max": 4}}))
        self.assertFalse(match_label_filters(labels, {"passenger_count": {"min": 4}}))
        self.assertTrue(match_label_filters(labels, {"passenger_count": {"max": 3}}))

    def test_and_across_labels(self) -> None:
        labels = {"day_period": "night", "seat": "rear"}
        self.assertTrue(
            match_label_filters(labels, {"day_period": "night", "seat": ["rear", "front"]})
        )
        self.assertFalse(
            match_label_filters(labels, {"day_period": "day", "seat": ["rear"]})
        )


class SemanticTextTests(unittest.TestCase):
    def test_substring_and_tokens(self) -> None:
        doc = "夜间后排有儿童，驾驶员专注看路"
        self.assertGreater(text_relevance_score("夜间儿童", doc), 0.5)
        self.assertGreater(
            text_relevance_score("夜间儿童", doc),
            text_relevance_score("高速公路拥堵", doc),
        )

    def test_irrelevant_query_text_score_near_zero(self) -> None:
        doc = "夜间后排有儿童，驾驶员专注看路"
        self.assertLess(text_relevance_score("量子泡沫xyz", doc), DEFAULT_MIN_TEXT_SCORE)
        # 「晚上」vs「夜间」无字面重叠时不应仅靠单字误命中到阈值以上
        self.assertLess(text_relevance_score("晚上", "白天高速行驶"), DEFAULT_MIN_TEXT_SCORE)

    def test_score_clip_candidate_label_and_semantic(self) -> None:
        labels = {
            "values": {
                "day_period": {"value": "night"},
                "scene_desc": {"value": "后排儿童夜间乘车"},
            }
        }
        hit = score_clip_candidate(
            labels_json=labels,
            scene_summary="后排儿童夜间乘车",
            label_filters={"day_period": ["night", "dusk"]},
            semantic_query="后排儿童",
            query_vec=None,
            min_semantic_score=DEFAULT_MIN_TEXT_SCORE,
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertGreaterEqual(hit["score"], DEFAULT_MIN_TEXT_SCORE)
        self.assertEqual(hit["match_mode"], "text")

        miss = score_clip_candidate(
            labels_json=labels,
            scene_summary="后排儿童夜间乘车",
            label_filters={"day_period": "day"},
            semantic_query="后排儿童",
            query_vec=None,
            min_semantic_score=DEFAULT_MIN_TEXT_SCORE,
        )
        self.assertIsNone(miss)

    def test_weak_positive_embedding_does_not_return_all(self) -> None:
        """Regression: cos_sim > 0 alone must not pass embed floor."""
        labels = {"values": {"scene_desc": {"value": "白天城市道路通勤"}}}
        query_vec = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        # Document vec weakly aligned with query — below embed floor.
        weak_doc = np.array([0.2, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        miss = score_clip_candidate(
            labels_json=labels,
            scene_summary="白天城市道路通勤",
            label_filters=None,
            semantic_query="晚上",
            query_vec=query_vec,
            document_vec=weak_doc,
            min_semantic_score=DEFAULT_MIN_TEXT_SCORE,
            min_embed_score=DEFAULT_MIN_EMBED_SCORE,
        )
        self.assertIsNone(miss)

        strong_doc = np.array([1.0, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        hit = score_clip_candidate(
            labels_json=labels,
            scene_summary="白天城市道路通勤",
            label_filters=None,
            semantic_query="晚上",
            query_vec=query_vec,
            document_vec=strong_doc,
            min_semantic_score=DEFAULT_MIN_TEXT_SCORE,
            min_embed_score=DEFAULT_MIN_EMBED_SCORE,
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["match_mode"], "embedding")
        self.assertGreaterEqual(hit["score"], DEFAULT_MIN_EMBED_SCORE)

    def test_clip_fusion_vector_json_is_ignored(self) -> None:
        """Passing legacy clip fusion vector_json must not create an embedding hit."""
        labels = {"values": {"scene_desc": {"value": "白天城市道路通勤"}}}
        query_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        fusion = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        miss = score_clip_candidate(
            labels_json=labels,
            scene_summary="白天城市道路通勤",
            vector_json=json.dumps(fusion.tolist()),
            label_filters=None,
            semantic_query="晚上",
            query_vec=query_vec,
            document_vec=None,
            min_semantic_score=DEFAULT_MIN_TEXT_SCORE,
            min_embed_score=DEFAULT_MIN_EMBED_SCORE,
        )
        self.assertIsNone(miss)

    def test_relevant_text_query_hits_without_embedding(self) -> None:
        labels = {"values": {"scene_desc": {"value": "夜间后排有儿童"}}}
        hit = score_clip_candidate(
            labels_json=labels,
            scene_summary="夜间后排有儿童",
            label_filters=None,
            semantic_query="夜间儿童",
            query_vec=None,
            min_semantic_score=DEFAULT_MIN_TEXT_SCORE,
        )
        self.assertIsNotNone(hit)

        nonsense = score_clip_candidate(
            labels_json=labels,
            scene_summary="夜间后排有儿童",
            label_filters=None,
            semantic_query="量子泡沫xyz",
            query_vec=None,
            min_semantic_score=DEFAULT_MIN_TEXT_SCORE,
        )
        self.assertIsNone(nonsense)

    def test_relative_cutoff_drops_long_tail(self) -> None:
        items = [
            {"clip_id": "a", "score": 0.90},
            {"clip_id": "b", "score": 0.88},
            {"clip_id": "c", "score": 0.50},
            {"clip_id": "d", "score": 0.40},
        ]
        kept = apply_semantic_rank_cutoff(items, relative_cutoff=0.85, top_k=10)
        ids = {x["clip_id"] for x in kept}
        self.assertEqual(ids, {"a", "b"})

    def test_flat_mid_scores_return_empty(self) -> None:
        """Corpus-wide weak positive sims must not all pass as 'matches'."""
        items = [
            {"clip_id": "a", "score": 0.42},
            {"clip_id": "b", "score": 0.41},
            {"clip_id": "c", "score": 0.40},
        ]
        kept = apply_semantic_rank_cutoff(items, relative_cutoff=0.85, top_k=10)
        self.assertEqual(kept, [])

    def test_normalize_label_filters(self) -> None:
        raw = {
            "a": ["x", "y"],
            "b": {"min": 1, "max": 3},
            "c": "",
            "d": {"in": ["p"]},
        }
        out = normalize_label_filters(raw)
        self.assertEqual(out["a"], ["x", "y"])
        self.assertEqual(out["b"]["min"], 1)
        self.assertEqual(out["d"]["in"], ["p"])
        self.assertNotIn("c", out)


if __name__ == "__main__":
    unittest.main()
