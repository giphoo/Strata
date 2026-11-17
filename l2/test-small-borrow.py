#!/usr/bin/env python3
"""Unit contracts for the P0/P1 small-borrow gateway policy (no engine needed)."""
import importlib.util
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gateway2", ROOT / "l2" / "gateway2.py")
gw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gw)


class AncestorSelectionTests(unittest.TestCase):
    def tearDown(self):
        gw.fam_idx.clear()
        gw._borrow_hotspots.clear()

    def test_equal_lineage_prefers_smaller_sufficient_archive(self):
        gw.fam_idx["f"] = {
            "large-chain": {"file": "large", "tok": 277000, "ts": 2,
                             "hashes": ["system", "parent-head", "parent-tail"]},
            "small-chain": {"file": "small", "tok": 29000, "ts": 1,
                             "hashes": ["system", "parent-head"]},
        }
        incoming = ["system", "parent-head", "new-fork"]
        self.assertEqual(gw.ancestor_snap("f", incoming)["file"], "small")
        self.assertEqual(gw.ancestor_snap_global(incoming)["file"], "small")

    def test_deeper_lineage_still_wins_over_smaller_archive(self):
        gw.fam_idx["f"] = {
            "large-chain": {"file": "large", "tok": 277000, "ts": 1,
                             "hashes": ["system", "parent-head", "parent-tail"]},
            "small-chain": {"file": "small", "tok": 29000, "ts": 2,
                             "hashes": ["system", "parent-head"]},
        }
        incoming = ["system", "parent-head", "parent-tail", "next-turn"]
        self.assertEqual(gw.ancestor_snap("f", incoming)["file"], "large")

    def test_exact_chain_is_never_replaced_by_a_smaller_ancestor(self):
        gw.fam_idx["f"] = {
            "large-chain": {"file": "large", "tok": 277000, "ts": 1, "hashes": ["system"]},
            "small-chain": {"file": "small", "tok": 1000, "ts": 2, "hashes": []},
        }
        self.assertEqual(gw.resolve_snap("f", "large-chain", ["system", "next"]), "large")


class BorrowHotspotTests(unittest.TestCase):
    def tearDown(self):
        gw._borrow_hotspots.clear()

    def test_classification_and_prefix_hint_use_verified_watermark(self):
        self.assertEqual(gw._classify_small_borrow(29341, 277000, 29100, 2, 4),
                         "small-borrow-big")
        self.assertIsNone(gw._classify_small_borrow(29341, 40000, 29100, 2, 4))
        self.assertIsNone(gw._classify_small_borrow(29341, 277000, 1000, 2, 4))

        body = {"messages": [{"role": "system"}, {"role": "user"}, {"role": "user"}]}
        hotspot = None
        for _ in range(2):
            hotspot = gw._remember_borrow_hotspot("f", 1, 1200)
        gw.BORROW_HOTSPOT_HITS = 2
        hint = gw._inject_borrow_prefix_hint(body, "f", hotspot, 2000)
        self.assertEqual(hint, {"kind": "tokens", "tokens": 1200, "hits": 2})
        self.assertEqual(body["strata_prefix"], {"tokens": 1200})

    def test_client_prefix_is_never_overridden(self):
        body = {"messages": [], "strata_prefix": {"messages": 1}}
        hotspot = gw._remember_borrow_hotspot("f", 1, 10)
        gw.BORROW_HOTSPOT_HITS = 1
        self.assertIsNone(gw._inject_borrow_prefix_hint(body, "f", hotspot, 20))
        self.assertEqual(body["strata_prefix"], {"messages": 1})

    def test_message_boundary_is_the_fallback(self):
        body = {"messages": [{"role": "system"}, {"role": "user"}]}
        hotspot = None
        for _ in range(2):
            hotspot = gw._remember_borrow_hotspot("f", 1, 0)
        gw.BORROW_HOTSPOT_HITS = 2
        hint = gw._inject_borrow_prefix_hint(body, "f", hotspot, 100)
        self.assertEqual(hint, {"kind": "messages", "messages": 1, "hits": 2})
        self.assertEqual(body["strata_prefix"], {"messages": 1})


class RestoreMetricTests(unittest.TestCase):
    def test_prefix_restore_fields_are_separate_from_legacy_archive_size(self):
        decision = {}
        js = {"n_read": 10 * 1024**2, "n_restored": 29000, "partial": True,
              "timings": {"restore_ms": 500},
              "prefix_checkpoint_tokens": 29184,
              "prefix_image_bytes": 3 * 1024**2,
              "prefix_payload_read_bytes": 4 * 1024**2,
              "prefix_block_read_bytes": 2 * 1024**2,
              "archive_format": "v3"}
        gw._record_restore_metrics(decision, js)
        self.assertEqual(decision["restore_n_read"], 10 * 1024**2)
        self.assertEqual(decision["restore_checkpoint_tokens"], 29184)
        self.assertEqual(decision["restore_io_read_bytes"], 2 * 1024**2)
        self.assertEqual(decision["restore_archive_format"], "v3")
        self.assertEqual(decision["restore_read_mib_s"], 20.0)
        self.assertEqual(decision["restore_io_read_mib_s"], 4.0)


if __name__ == "__main__":
    unittest.main()
