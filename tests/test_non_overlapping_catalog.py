"""The generated rule catalog must not contain nested literals.

A literal occurring inside another literal guarantees overlapping matches
wherever the outer one appears, and the two engines resolve overlap differently
(ENGINE-SEMANTICS ES-1), so a document carrying the outer literal has two
defensible answers and cannot check either engine's output.

Enforced in two places: the catalog builder skips a value that nests with one
already accepted for the same pattern, and generation refuses a catalog that
still contains a nested pair across patterns.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from framework.policy.matching import LiteralMatcher, overlapping_matches
from framework.policy.overlap import find_contained_literals
from framework.workload.generate_scale_artifacts import (
    _unique_rule_value,
    generate_scale_artifacts,
    supported_patterns,
)

ALL_PATTERNS = supported_patterns()


class ContainmentDetectionTests(unittest.TestCase):
    def test_detects_nested_literal(self) -> None:
        found = find_contained_literals(["Elena Chen", "Elena Chen 1327"])
        self.assertEqual(found, [("Elena Chen", "Elena Chen 1327")])

    def test_ignores_disjoint_literals(self) -> None:
        self.assertEqual(find_contained_literals(["ABCD", "WXYZ"]), [])

    def test_ignores_suffix_prefix_join(self) -> None:
        # Theoretically overlappable but requires the literals to abut in the
        # input; never observed on generated corpora.
        self.assertEqual(find_contained_literals(["ABCD", "DEFG"]), [])

    def test_detects_interior_containment(self) -> None:
        found = find_contained_literals(["mid", "XmidY"])
        self.assertEqual(found, [("mid", "XmidY")])


class RuleValueShapeTests(unittest.TestCase):
    """The catalog builder, which is where the invariant is enforced.

    Individual value shapes are realistic and so a few of them CAN nest - a real
    address list holds 10.1.2.3 and 110.1.2.3, a real name list holds "Elena
    Chen" and "Elena Chen Jr." - so the check belongs on the built catalog, not
    on the generator. `_unique_rule_value` skips a value that nests with one
    already accepted for the same pattern, which is where the risk lives.
    """

    def values(self, pattern: str, count: int = 600) -> list[str]:
        """Values as the catalog builder would accept them for one pattern."""
        used: set[str] = set()
        accepted: list[str] = []
        for index in range(1, count):
            value = _unique_rule_value(pattern, index, used, accepted, count)
            used.add(value)
            accepted.append(value)
        return accepted

    def test_person_names_are_not_nested(self) -> None:
        self.assertEqual(find_contained_literals(self.values("person_name")), [])

    def test_street_addresses_are_not_nested(self) -> None:
        self.assertEqual(find_contained_literals(self.values("street_address")), [])

    def test_ipv4_addresses_are_not_nested(self) -> None:
        self.assertEqual(find_contained_literals(self.values("ipv4_address")), [])

    def test_ipv6_addresses_are_not_nested(self) -> None:
        self.assertEqual(find_contained_literals(self.values("ipv6_address")), [])

    def test_person_name_values_remain_unique(self) -> None:
        values = self.values("person_name")
        self.assertEqual(len(values), len(set(values)))

    def test_no_pattern_produces_a_nested_catalog(self) -> None:
        """Every supported pattern, not only the ones known to have failed.

        Checking patterns individually is whack-a-mole: the original fix was
        applied to four generators and a fifth, internal_product_name, was only
        caught when generation refused a real catalog.
        """
        every_value: list[str] = []
        for pattern in ALL_PATTERNS:
            values = self.values(pattern, count=400)
            with self.subTest(pattern=pattern):
                self.assertEqual(
                    find_contained_literals(values),
                    [],
                    f"{pattern} produces a nested catalog",
                )
            every_value.extend(values)

        # Also across families - a literal from one pattern must not sit
        # inside a literal from another. Nothing dedupes across patterns during
        # generation, so this is the case the whole-catalog guard exists for.
        self.assertEqual(find_contained_literals(every_value), [])


class GenerationRefusesNestedCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def workload(self) -> dict:
        return {
            "schema": "enterprise-dlp-scale",
            "name": "overlap-free",
            "seed": 42,
            "policy": {
                "rule_count": 500,
                "families": {
                    "pii": {
                        "weight": 100,
                        "patterns": ["person_name", "street_address"],
                    }
                },
            },
            "documents": {
                "count": 60,
                "progress_interval_records": 100,
                "scenarios": {
                    "customer_record": {
                        "weight": 100,
                        "fields": ["customer_id", "person_name", "street_address"],
                    }
                },
                "formats": {"json": {"weight": 100}},
                "match_distribution": {
                    "clean": {
                        "weight": 30,
                        "matches_per_document": {"minimum": 0, "maximum": 0},
                    },
                    "dirty": {
                        "weight": 70,
                        "matches_per_document": {"minimum": 1, "maximum": 3},
                    },
                },
                "size_distribution": {
                    "small": {
                        "weight": 100,
                        "minimum_bytes": 200,
                        "maximum_bytes": 400,
                    }
                },
                "generate_clean_control_records": True,
            },
        }

    def generate(self, workload: dict, name: str):
        config = self.root / f"{name}.yaml"
        config.write_text(yaml.safe_dump(workload, sort_keys=False), encoding="utf-8")
        return generate_scale_artifacts(config, self.root / name)

    def test_catalog_at_scale_has_no_nested_literals(self) -> None:
        manifest = self.generate(self.workload(), "clean-catalog")
        variants = [rule["variant"] for rule in manifest["rule_catalog"]]
        self.assertEqual(find_contained_literals(variants), [])

    def test_generated_corpus_has_no_overlapping_matches(self) -> None:
        """The property that actually matters: no document contains overlaps."""
        import json

        manifest = self.generate(self.workload(), "clean-corpus")
        self.assertEqual(manifest["overlapping_match_documents"], 0)

        variants = [rule["variant"] for rule in manifest["rule_catalog"]]
        matcher = LiteralMatcher(variants)
        corpus = (self.root / "clean-corpus" / "input.jsonl").read_text()
        for line in corpus.splitlines():
            row = json.loads(line)
            self.assertEqual(
                overlapping_matches(matcher.find_all(row["message"])),
                [],
                f"{row['record_id']} contains overlapping matches",
            )


if __name__ == "__main__":
    unittest.main()
