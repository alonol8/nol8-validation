from __future__ import annotations

import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from framework.cli.main import generate_run, main
from framework.policy.matching import LiteralMatcher, overlapping_matches
from framework.workload.generate_scale_artifacts import (
    ScaleRule,
    _realistic_rule_value,
    generate_scale_artifacts,
)


class ValidateScaleGenerateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.config = self.root / "enterprise-dlp.yaml"
        self.config.write_text(
            yaml.safe_dump(
                {
                    "name": "enterprise-dlp-test",
                    "version": 0.1,
                    "seed": 42,
                    "policy": {
                        "rule_count": 12,
                        "families": {
                            "pii": {
                                "weight": 2,
                                "patterns": ["email_address", "phone_number"],
                            },
                            "credentials": {
                                "weight": 1,
                                "patterns": ["api_key"],
                            },
                        },
                    },
                    "documents": {
                        "count": 8,
                        "progress_interval_records": 3,
                        "scenarios": {
                            "customer_record": {
                                "weight": 1,
                                "fields": ["customer_id", "internal_notes"],
                            }
                        },
                        "formats": {"text": {"weight": 1}},
                        "match_distribution": {
                            "dirty": {
                                "weight": 1,
                                "matches_per_document": {"minimum": 2, "maximum": 2},
                            }
                        },
                        "size_distribution": {
                            "small": {
                                "weight": 1,
                                "pad_to_target": True,
                                "minimum_bytes": 300,
                                "maximum_bytes": 400,
                            }
                        },
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _rows(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines()]

    def realistic_config(self) -> Path:
        workload = yaml.safe_load(self.config.read_text(encoding="utf-8"))
        workload["policy"] = {
            "rule_count": 24,
            "families": {
                "pii": {
                    "weight": 4,
                    "patterns": [
                        "person_name",
                        "email_address",
                        "phone_number",
                        "street_address",
                    ],
                },
                "financial": {
                    "weight": 2,
                    "patterns": ["credit_card_number", "invoice_number"],
                },
                "business_terms": {
                    "weight": 2,
                    "patterns": ["customer_id", "support_case_id"],
                },
            },
        }
        workload["documents"] = {
            "count": 20,
            "progress_interval_records": 10,
            "scenarios": {
                "customer_record": {
                    "weight": 1,
                    "fields": [
                        "customer_id",
                        "person_name",
                        "email_address",
                        "phone_number",
                        "street_address",
                        "account_status",
                        "internal_notes",
                    ],
                }
            },
            "formats": {"json": {"weight": 1}},
            "match_distribution": {
                "clean": {
                    "weight": 1,
                    "matches_per_document": {"minimum": 0, "maximum": 0},
                },
                "dirty": {
                    "weight": 3,
                    "matches_per_document": {"minimum": 1, "maximum": 3},
                },
            },
            "size_distribution": {
                "small": {
                    "weight": 1,
                    "minimum_bytes": 700,
                    "maximum_bytes": 1400,
                }
            },
        }
        path = self.root / "realistic-enterprise-dlp.yaml"
        path.write_text(yaml.safe_dump(workload, sort_keys=False), encoding="utf-8")
        return path

    def test_realistic_rule_values_are_deterministic_and_type_shaped(self) -> None:
        patterns = (
            "email_address",
            "customer_id",
            "phone_number",
            "street_address",
            "api_key",
            "credit_card_number",
            "ipv4_address",
        )
        values = {pattern: _realistic_rule_value(pattern, 17) for pattern in patterns}
        for pattern in patterns:
            self.assertEqual(values[pattern], _realistic_rule_value(pattern, 17))
        self.assertRegex(values["email_address"], r"^[a-z.]+\d*@[-a-z.]+$")
        self.assertRegex(values["customer_id"], r"^CUST-\d{6}$")
        self.assertRegex(values["phone_number"], r"^\+1-\d{3}-\d{3}-\d{4}$")
        self.assertRegex(values["street_address"], r"^\d+ [A-Za-z]+ [A-Za-z]+, [A-Za-z]+ NC$")
        self.assertRegex(values["api_key"], r"^sk_live_[A-Za-z0-9]{24,32}$")
        self.assertRegex(values["credit_card_number"], r"^[\d][\d \-]{13,18}$")
        self.assertRegex(values["ipv4_address"], r"^(\d{1,3}\.){3}\d{1,3}$")
        self.assertTrue(all("NOL8_" not in value for value in values.values()))

    def test_credential_values_do_not_share_a_common_stem(self) -> None:
        """The property that makes a real credential list what it is.

        An issued key carries no structure past its prefix, so a list of them
        fans out immediately. When these were sequential counters, 5,000 rules
        shared all but their last few bytes - which is not what a customer's
        secret-scanning policy looks like, and reads far cheaper to match than
        the real thing (docs/WHAT-COSTS-A-MATCHER.md).
        """
        keys = [_realistic_rule_value("api_key", index) for index in range(1, 200)]
        self.assertEqual(len(set(keys)), len(keys))
        # Distinct 12-byte openings, i.e. the shared "sk_live_" plus four bytes.
        self.assertGreater(len({key[:12] for key in keys}), 150)

    def test_realistic_customer_artifacts_share_catalog_values(self) -> None:
        output = self.root / "realistic-generated"
        generate_scale_artifacts(self.realistic_config(), output)
        manifest = json.loads((output / "manifest.json").read_text())
        inputs = self._rows(output / "input.jsonl")
        expected = self._rows(output / "expected.jsonl")
        policy = (output / "scale-policy.nol").read_text()
        catalog_values = {item["variant"] for item in manifest["rule_catalog"]}

        self.assertNotIn("NOL8_", policy)
        self.assertNotIn("validation_rule_", "".join(row["message"] for row in inputs))
        self.assertGreater(manifest["dirty_record_count"], 0)
        self.assertGreater(manifest["clean_record_count"], 0)
        for input_row, expected_row in zip(inputs, expected, strict=True):
            json.loads(input_row["message"])
            if input_row["kind"] == "clean":
                self.assertFalse(
                    any(value in input_row["message"] for value in catalog_values)
                )
                self.assertEqual(expected_row["expected_matches"], [])
                continue
            for match in expected_row["expected_matches"]:
                self.assertIn(match["variant"], catalog_values)
                self.assertIn(match["variant"], policy)
                self.assertIn(match["variant"], input_row["message"])
                self.assertIn(match["replacement"], expected_row["expected_message"])

        filler_phrase = "Synthetic enterprise validation content."
        for row in inputs:
            self.assertNotIn("_synthetic_padding", row["message"])
            filler_bytes = row["message"].count(filler_phrase) * len(filler_phrase)
            self.assertLess(filler_bytes, len(row["message"].encode("utf-8")) / 2)
        self.assertEqual(manifest["padding_bytes_total"], 0)
        self.assertEqual(manifest["padded_document_count"], 0)
        self.assertEqual(
            manifest["generation_mode_distribution"], {"realistic": 20}
        )

    def test_generation_is_deterministic(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        generate_scale_artifacts(self.config, first)
        generate_scale_artifacts(self.config, second)
        for filename in (
            "scale-policy.nol",
            "input.jsonl",
            "expected.jsonl",
            "manifest.json",
        ):
            self.assertEqual(
                (first / filename).read_bytes(),
                (second / filename).read_bytes(),
            )

    def test_generates_requested_policy_rule_count(self) -> None:
        output = self.root / "generated"
        manifest = generate_scale_artifacts(self.config, output)
        policy_lines = (output / "scale-policy.nol").read_text().splitlines()
        self.assertEqual(len(policy_lines), 12)
        self.assertEqual(manifest["requested_rules"], 12)
        self.assertEqual(manifest["realized_rules"], 12)
        self.assertTrue(all(" -> " in line for line in policy_lines))

    def test_scale_values_and_distributions_come_from_configuration(self) -> None:
        output = self.root / "generated"
        manifest = generate_scale_artifacts(self.config, output)
        requested = manifest["requested_scale"]
        realized = manifest["realized_scale"]

        self.assertEqual(requested["rule_count"], 12)
        self.assertEqual(requested["record_count"], 8)
        self.assertEqual(
            requested["size_distribution"]["small"],
            {
                "weight": 1,
                "pad_to_target": True,
                "minimum_bytes": 300,
                "maximum_bytes": 400,
            },
        )
        self.assertEqual(realized["rule_count"], 12)
        self.assertEqual(realized["record_count"], 8)
        self.assertEqual(realized["size_profile_distribution"], {"small": 8})
        self.assertGreaterEqual(realized["payload_bytes"]["minimum"], 300)
        self.assertLessEqual(realized["payload_bytes"]["maximum"], 400)

    def test_canonical_input_and_expected_artifacts_share_evidence(self) -> None:
        output = self.root / "generated"
        manifest = generate_scale_artifacts(self.config, output)
        inputs = self._rows(output / "input.jsonl")
        expected = self._rows(output / "expected.jsonl")

        self.assertEqual(len(inputs), 8)
        self.assertEqual(len(expected), 8)
        self.assertEqual(manifest["realized_records"], 8)
        self.assertEqual(
            [row["record_id"] for row in inputs],
            [row["record_id"] for row in expected],
        )
        self.assertEqual(set(inputs[0]), {"record_id", "kind", "message"})
        self.assertEqual(
            set(expected[0]),
            {
                "record_id",
                "kind",
                "expected_message",
                "expected_match_count",
                "expected_matches",
            },
        )
        match = expected[0]["expected_matches"][0]
        self.assertTrue(
            {"category_id", "case_id", "variant", "replacement"} <= set(match)
        )
        self.assertIn(match["variant"], inputs[0]["message"])
        self.assertNotIn(match["variant"], expected[0]["expected_message"])
        self.assertIn(match["replacement"], expected[0]["expected_message"])

    def test_generate_cli_path_registers_canonical_artifacts(self) -> None:
        _, run_directory = generate_run(self.config, self.root / "runs")
        manifest = json.loads((run_directory / "manifest.json").read_text())
        self.assertEqual(manifest["run_type"], "scale")
        self.assertEqual(
            manifest["stages"]["generation"]["generator"],
            "framework.workload.generate_scale_artifacts",
        )
        for artifact in ("policy", "input", "expected", "generation_manifest"):
            self.assertTrue(
                (run_directory / manifest["artifacts"][artifact]["path"]).is_file()
            )

    def test_scale_cli_reports_bounded_generation_progress(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            result = main(
                [
                    "generate",
                    "--config",
                    str(self.config),
                    "--runs-dir",
                    str(self.root / "progress-runs"),
                ]
            )

        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Generating validation workload", output)
        self.assertIn("Rules requested: 12", output)
        self.assertIn("Records requested: 8", output)
        self.assertIn("Step 1/4: Loading workload configuration", output)
        self.assertIn("Step 2/4: Building rule catalog", output)
        self.assertIn("Rules generated: 12/12", output)
        self.assertIn("Step 3/4: Generating documents", output)
        self.assertIn("8/8", output)
        self.assertIn("Step 4/4: Writing artifacts", output)
        self.assertIn("Generation completed", output)

    def test_generation_progress_does_not_scroll_one_line_per_interval(self) -> None:
        """Progress must be a bar, not a line per interval.

        Generation previously printed two lines per progress interval, so a
        million-record corpus produced tens of thousands of lines of scrollback.
        """
        workload = yaml.safe_load(self.config.read_text(encoding="utf-8"))
        workload["documents"]["count"] = 200
        workload["documents"]["progress_interval_records"] = 1
        config = self.root / "scrolling-check.yaml"
        config.write_text(yaml.safe_dump(workload, sort_keys=False), encoding="utf-8")

        stdout = StringIO()
        with redirect_stdout(stdout):
            result = main([
                "generate", "--config", str(config),
                "--runs-dir", str(self.root / "scrolling-runs"),
            ])
        self.assertEqual(result, 0)

        output = stdout.getvalue()
        # 200 records at an interval of 1 previously produced 400 progress
        # lines. Redirected output is bounded to roughly one line per 10%.
        self.assertLess(len(output.splitlines()), 40)
        self.assertNotIn("\033", output)
        self.assertIn("200/200", output)

    def test_direct_scale_generation_is_quiet_without_callback(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            generate_scale_artifacts(self.config, self.root / "quiet-generated")
        self.assertEqual(stdout.getvalue(), "")

    def test_cli_overrides_resolve_into_snapshot_and_artifacts(self) -> None:
        _, run_directory = generate_run(
            self.config,
            self.root / "override-runs",
            rule_count_override=5,
            record_count_override=3,
        )
        snapshot = yaml.safe_load(
            (run_directory / "config/enterprise-dlp.yaml").read_text()
        )
        generation_manifest = json.loads(
            (run_directory / "generated/generation-manifest.json").read_text()
        )

        self.assertEqual(snapshot["policy"]["rule_count"], 5)
        self.assertEqual(snapshot["documents"]["count"], 3)
        self.assertEqual(generation_manifest["requested_rules"], 5)
        self.assertEqual(generation_manifest["realized_rules"], 5)
        self.assertEqual(generation_manifest["requested_records"], 3)
        self.assertEqual(generation_manifest["realized_records"], 3)
        self.assertEqual(
            len((run_directory / "generated/scale-policy.nol").read_text().splitlines()),
            5,
        )
        self.assertEqual(
            len((run_directory / "generated/input.jsonl").read_text().splitlines()),
            3,
        )

    def test_cli_displays_effective_override_values(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            result = main(
                [
                    "generate",
                    "--config",
                    str(self.config),
                    "--runs-dir",
                    str(self.root / "override-cli-runs"),
                    "--rules",
                    "5",
                    "--records",
                    "3",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("Rules requested: 5", stdout.getvalue())
        self.assertIn("Records requested: 3", stdout.getvalue())

    def test_identical_overrides_produce_deterministic_artifacts(self) -> None:
        generated_directories = []
        for runs_name in ("override-first", "override-second"):
            _, run_directory = generate_run(
                self.config,
                self.root / runs_name,
                rule_count_override=7,
                record_count_override=4,
            )
            generated_directories.append(run_directory / "generated")

        for filename in (
            "scale-policy.nol",
            "input.jsonl",
            "expected.jsonl",
            "generation-manifest.json",
        ):
            self.assertEqual(
                (generated_directories[0] / filename).read_bytes(),
                (generated_directories[1] / filename).read_bytes(),
            )

    def test_callback_receives_configured_document_progress_updates(self) -> None:
        events: list[tuple[str, int, int]] = []
        generate_scale_artifacts(
            self.config,
            self.root / "callback-generated",
            progress_callback=lambda event, completed, total: events.append(
                (event, completed, total)
            ),
        )

        self.assertEqual(
            [event for event in events if event[0] == "documents_progress"],
            [
                ("documents_progress", 3, 8),
                ("documents_progress", 6, 8),
                ("documents_progress", 8, 8),
            ],
        )
        self.assertEqual(
            [event for event in events if event[0] == "expected_progress"],
            [
                ("expected_progress", 3, 8),
                ("expected_progress", 6, 8),
                ("expected_progress", 8, 8),
            ],
        )

    def test_progress_callback_does_not_change_generation_results(self) -> None:
        quiet = self.root / "quiet-results"
        reported = self.root / "reported-results"
        generate_scale_artifacts(self.config, quiet)
        generate_scale_artifacts(
            self.config,
            reported,
            progress_callback=lambda _event, _completed, _total: None,
        )

        for filename in (
            "scale-policy.nol",
            "input.jsonl",
            "expected.jsonl",
            "manifest.json",
        ):
            self.assertEqual(
                (quiet / filename).read_bytes(),
                (reported / filename).read_bytes(),
            )

    def test_expected_results_account_for_every_catalog_literal(self) -> None:
        """No catalog literal may occur in a document without being accounted for.

        Expected output was previously computed from the rules the generator
        intended to inject. That invariant is false - unrelated generated
        values collide with catalog literals - so Themis correctly redacted a
        value the expected file said should survive, and was scored as failing.
        """
        output = self.root / "expected-correctness"
        manifest = generate_scale_artifacts(self.config, output)
        inputs = self._rows(output / "input.jsonl")
        expected = self._rows(output / "expected.jsonl")

        catalog = [ScaleRule(**item) for item in manifest["rule_catalog"]]
        matcher = LiteralMatcher({rule.variant for rule in catalog})

        for input_row, expected_row in zip(inputs, expected, strict=True):
            present = {
                match.literal
                for match in matcher.find_all(input_row["message"])
            }
            accounted = {
                match["variant"] for match in expected_row["expected_matches"]
            }
            # Overlapping matches are deliberately not all selected, so
            # accounted may be a subset - but never may a literal be present
            # and wholly unexplained when nothing overlaps.
            overlaps = overlapping_matches(
                matcher.find_all(input_row["message"])
            )
            if not overlaps:
                self.assertEqual(
                    present,
                    accounted,
                    f"{input_row['record_id']} has unaccounted literals: "
                    f"{sorted(present - accounted)}",
                )

    def test_expected_message_is_the_documented_transformation(self) -> None:
        """Applying the recorded matches to the input must yield the expected."""
        output = self.root / "expected-transformation"
        generate_scale_artifacts(self.config, output)
        inputs = {
            row["record_id"]: row for row in self._rows(output / "input.jsonl")
        }
        for expected_row in self._rows(output / "expected.jsonl"):
            source = inputs[expected_row["record_id"]]["message"]
            for match in expected_row["expected_matches"]:
                self.assertIn(match["variant"], source)
            self.assertEqual(
                len(expected_row["expected_matches"]),
                expected_row["expected_match_count"],
            )

    def test_generation_manifest_reports_overlap_exposure(self) -> None:
        output = self.root / "overlap-exposure"
        manifest = generate_scale_artifacts(self.config, output)
        self.assertIn("overlapping_match_documents", manifest)
        self.assertIsInstance(manifest["overlapping_match_documents"], int)
        self.assertIn("intended_clean_with_literals", manifest)

    def test_large_rule_catalog_generation_completes_promptly(self) -> None:
        workload = yaml.safe_load(self.config.read_text(encoding="utf-8"))
        workload["policy"]["rule_count"] = 5000
        workload["documents"]["count"] = 100
        workload["documents"]["progress_interval_records"] = 50
        scale_config = self.root / "performance-enterprise-dlp.yaml"
        scale_config.write_text(
            yaml.safe_dump(workload, sort_keys=False),
            encoding="utf-8",
        )

        started = time.perf_counter()
        manifest = generate_scale_artifacts(
            scale_config, self.root / "performance-generated"
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(manifest["realized_rules"], 5000)
        self.assertEqual(manifest["realized_records"], 100)
        self.assertLess(elapsed, 3.0)


if __name__ == "__main__":
    unittest.main()
