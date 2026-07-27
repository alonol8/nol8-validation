"""Almost-matching text must almost match, and must never actually match."""
from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

import yaml

from framework.policy.matching import LiteralMatcher
from framework.workload.generate_scale_artifacts import generate_scale_artifacts
from framework.workload.near_miss import NearMissFactory, NearMissSupply, parse_density


CATALOG = {
    "customer_id": ["CUST-000123", "CUST-000124", "CUST-000125"],
    "api_key": ["sk_test_enterprise_000123", "sk_test_enterprise_000200"],
    "credit_card_number": ["4111-1111-0076-0532"],
    "internal_product_name": ["Northstar Suite 00135"],
    "person_name": ["Sandra Hernandez 00042"],
}

ALL_LITERALS = [value for values in CATALOG.values() for value in values]


def _factory() -> NearMissFactory:
    return NearMissFactory(LiteralMatcher(ALL_LITERALS), CATALOG)


class NearMissGenerationTests(unittest.TestCase):
    def test_no_derived_value_matches_the_catalog(self) -> None:
        """The one guarantee everything else rests on.

        Truncating or altering a governed value can land on another governed
        value - most easily where identifiers are issued in sequence, which is
        the common case. A near miss that is silently a match would be recorded
        as text that should survive while the engine correctly redacts it.
        """
        matcher = LiteralMatcher(ALL_LITERALS)
        pool = _factory().build_pool(400, random.Random(11))
        self.assertGreater(len(pool), 50, "pool should not be nearly empty")
        for near_miss in pool:
            self.assertEqual(
                matcher.find_all(near_miss.value),
                [],
                f"{near_miss.value!r} ({near_miss.kind}) matches the catalog",
            )

    def test_derived_values_resemble_the_value_they_came_from(self) -> None:
        """A near miss shares a long prefix; an unrelated value does not.

        This is the difference between "another customer's ID" and a near miss.
        Both are ungoverned, but only one of them exercises what happens when
        text nearly matches a rule.
        """
        pool = _factory().build_pool(300, random.Random(3))
        shares_long_prefix = 0
        for near_miss in pool:
            best = max(
                len(_common_prefix(near_miss.value, literal))
                for literal in ALL_LITERALS
            )
            if best >= max(6, int(len(near_miss.value) * 0.7)):
                shares_long_prefix += 1
        self.assertGreater(
            shares_long_prefix,
            int(len(pool) * 0.8),
            "most near misses should share a long prefix with a governed value",
        )

    def test_sequential_neighbour_is_produced(self) -> None:
        """The commonest real case: the record issued next to a watched one."""

        factory = _factory()
        rng = random.Random(5)
        altered = [
            factory.altered_tail("sk_test_enterprise_000123", rng) for _ in range(40)
        ]
        produced = {near_miss.value for near_miss in altered if near_miss is not None}
        self.assertTrue(produced, "altered_tail produced nothing")
        for value in produced:
            self.assertEqual(len(value), len("sk_test_enterprise_000123"))
            self.assertTrue(value.startswith("sk_test_enterprise_0001"[:18]))

    def test_truncation_is_a_prefix_of_the_original(self) -> None:
        factory = _factory()
        rng = random.Random(9)
        for _ in range(40):
            near_miss = factory.truncated("sk_test_enterprise_000123", rng)
            if near_miss is None:
                continue
            self.assertTrue("sk_test_enterprise_000123".startswith(near_miss.value))
            self.assertLess(len(near_miss.value), len("sk_test_enterprise_000123"))

    def test_word_variant_drops_a_qualifier(self) -> None:
        """The oldest failure in list matching: "Acme Corp" vs "Acme Corporation"."""

        factory = _factory()
        rng = random.Random(2)
        produced = {
            near_miss.value
            for near_miss in (
                factory.word_variant("Northstar Suite 00135", rng) for _ in range(60)
            )
            if near_miss is not None
        }
        self.assertIn("Northstar Suite", produced)

    def test_supply_respects_its_budget(self) -> None:
        pool = _factory().build_pool(80, random.Random(1))
        supply = NearMissSupply(pool, random.Random(1), budget=5)
        self.assertEqual(len(supply.take(50)), 5)
        self.assertEqual(supply.used, 5)
        self.assertEqual(supply.take(1), [])

    def test_absent_configuration_disables_the_feature(self) -> None:
        self.assertIsNone(parse_density(None))
        self.assertEqual(
            parse_density({"per_kilobyte": {"minimum": 2, "maximum": 5}}), (2.0, 5.0)
        )

    def test_malformed_configuration_is_rejected(self) -> None:
        """A section that is present but says nothing is a mistake, not a default.

        Omitting it entirely disables the feature; writing it incompletely is
        almost always an editing error, and silently generating nothing would
        hide it.
        """
        for broken in ({}, {"per_kilobyte": {"minimum": 2}}, {"per_kilobyte": {"minimum": -1, "maximum": 5}}):
            with self.assertRaises(ValueError):
                parse_density(broken)


def _common_prefix(left: str, right: str) -> str:
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return left[:index]
    return left[:limit]


BASE_WORKLOAD: dict = {
    "name": "near-miss-test",
    "seed": 42,
    "policy": {
        "rule_count": 40,
        "families": {
            "pii": {
                "weight": 50,
                "patterns": ["person_name", "email_address", "phone_number"],
            },
            "business_terms": {
                "weight": 50,
                "patterns": ["customer_id", "support_case_id", "project_codename"],
            },
        },
    },
    "documents": {
        "count": 30,
        "progress_interval_records": 10,
        "near_miss_distribution": {"per_kilobyte": {"minimum": 4, "maximum": 8}},
        "scenarios": {
            "customer_record": {
                "weight": 50,
                "fields": ["customer_id", "person_name", "email_address", "internal_notes"],
            },
            "application_log": {
                "weight": 50,
                "fields": ["timestamp", "log_level", "hostname", "message"],
            },
        },
        "formats": {"json": {"weight": 100}},
        "match_distribution": {
            "clean": {"weight": 30, "matches_per_document": {"minimum": 0, "maximum": 0}},
            "light": {"weight": 70, "matches_per_document": {"minimum": 1, "maximum": 5}},
        },
        "size_distribution": {
            "small": {
                "weight": 100,
                "pad_to_target": True,
                "minimum_bytes": 1024,
                "maximum_bytes": 4096,
            }
        },
    },
}


class NearMissCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def _generate(self, workload: dict, name: str) -> tuple[dict, Path]:
        config = self.root / f"{name}.yaml"
        config.write_text(yaml.safe_dump(workload, sort_keys=False), encoding="utf-8")
        output = self.root / name
        manifest = generate_scale_artifacts(config, output)
        return manifest, output

    def test_expected_results_account_for_every_match_in_the_corpus(self) -> None:
        """The corpus stays honest with near misses present.

        Expected output is computed by scanning the finished document, so a near
        miss that turned out to be a match would still be handled correctly -
        but it would mean the corpus contains matches nobody intended. This
        recounts independently and requires the numbers to agree.
        """
        manifest, output = self._generate(BASE_WORKLOAD, "accounted")
        catalog = [rule["variant"] for rule in manifest["rule_catalog"]]
        matcher = LiteralMatcher(catalog)

        inputs = _read_jsonl(output / "input.jsonl")
        expected = _read_jsonl(output / "expected.jsonl")
        self.assertEqual(len(inputs), len(expected))

        for input_row, expected_row in zip(inputs, expected):
            found = matcher.find_all(input_row["message"])
            selected = _leftmost_longest(found)
            self.assertEqual(
                len(selected),
                expected_row["expected_match_count"],
                f"{input_row['record_id']}: expected evidence disagrees with a rescan",
            )

    def test_near_misses_are_present_at_roughly_the_configured_density(self) -> None:
        manifest, _ = self._generate(BASE_WORKLOAD, "density")
        profile = manifest["input_profile"]
        self.assertTrue(profile["near_miss_configured"])
        self.assertGreater(profile["near_miss_total"], 0)
        # Documents stop taking values when they reach their size target, so the
        # realised density sits at or below the configured band, never above it.
        self.assertLessEqual(profile["near_misses_per_kb"], 8.0)
        self.assertGreater(profile["near_misses_per_kb"], 0.5)

    def test_omitting_the_section_leaves_generation_unchanged(self) -> None:
        """A workload written before this option existed must be unaffected."""

        without = json.loads(json.dumps(BASE_WORKLOAD))
        del without["documents"]["near_miss_distribution"]
        manifest, output = self._generate(without, "without")
        self.assertFalse(manifest["input_profile"]["near_miss_configured"])
        self.assertEqual(manifest["input_profile"]["near_miss_total"], 0)

        manifest_again, output_again = self._generate(without, "without-again")
        self.assertEqual(
            (output / "input.jsonl").read_bytes(),
            (output_again / "input.jsonl").read_bytes(),
        )

    def test_generation_is_reproducible_with_near_misses_enabled(self) -> None:
        _, first = self._generate(BASE_WORKLOAD, "repro-one")
        _, second = self._generate(BASE_WORKLOAD, "repro-two")
        for filename in ("input.jsonl", "expected.jsonl", "scale-policy.nol"):
            self.assertEqual(
                (first / filename).read_bytes(),
                (second / filename).read_bytes(),
                f"{filename} differs between runs of the same seed",
            )

    def test_documents_do_not_contain_generator_markers(self) -> None:
        """Values arrive in context, not on labelled lines."""

        _, output = self._generate(BASE_WORKLOAD, "markers")
        text = (output / "input.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("validation_rule_", text)
        self.assertNotIn("validation_content", text)


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _leftmost_longest(matches) -> list:
    selected = []
    cursor = 0
    for match in sorted(matches, key=lambda item: (item.start, -item.length)):
        if match.start < cursor:
            continue
        selected.append(match)
        cursor = match.end
    return selected


if __name__ == "__main__":
    unittest.main()
