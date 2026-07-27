"""Deploying and inspecting policies through the CLI, not the transport scripts.

Restoring a policy previously required calling scripts/load-policy.sh directly,
which bypasses the product surface. `validate` is the interface; operating the
tool should never require dropping beneath it.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from framework.cli.main import (
    PolicyDeploymentError,
    apply_policy_file,
    build_parser,
    main,
    read_policy_deployments,
)

RESPONSE = {
    "ok": True,
    "command_id": "cmd-001",
    "stage": "apollo",
    "message": "loaded 3 rule(s)",
    "rules": 3,
}


class PolicyFileDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.policy = self.root / "restore.nol"
        self.policy.write_text('"a" -> "[A]";\n', encoding="utf-8")
        self.ledger = self.root / "artifacts" / "policy-deployments.jsonl"
        patcher = patch(
            "framework.cli.main._policy_ledger_path", return_value=self.ledger
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_deploys_a_policy_file_directly(self) -> None:
        with patch(
            "framework.cli.main.deploy_policy", return_value=(200, RESPONSE)
        ) as deploy:
            result = apply_policy_file(self.policy, "themis")
        deploy.assert_called_once()
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["response"]["rules"], 3)
        self.assertEqual(len(result["policy_sha256"]), 64)

    def test_missing_file_is_a_prerequisite_error(self) -> None:
        with self.assertRaises(PolicyDeploymentError) as caught:
            apply_policy_file(self.root / "absent.nol", "themis")
        self.assertEqual(caught.exception.category, "prerequisite")

    def test_deployment_is_recorded_in_the_ledger(self) -> None:
        with patch("framework.cli.main.deploy_policy", return_value=(200, RESPONSE)):
            apply_policy_file(self.policy, "themis")
        entries = read_policy_deployments()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "file")
        self.assertEqual(entries[0]["rule_count"], 3)
        self.assertEqual(entries[0]["target"], "themis")

    def test_ledger_returns_most_recent_first(self) -> None:
        with patch("framework.cli.main.deploy_policy", return_value=(200, RESPONSE)):
            apply_policy_file(self.policy, "themis")
            other = self.root / "second.nol"
            other.write_text('"b" -> "[B]";\n', encoding="utf-8")
            apply_policy_file(other, "themis")
        entries = read_policy_deployments()
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0]["policy_path"].endswith("second.nol"))

    def test_failed_deployment_is_not_recorded(self) -> None:
        with patch(
            "framework.cli.main.deploy_policy",
            side_effect=PolicyDeploymentError("network", "unreachable"),
        ):
            with self.assertRaises(PolicyDeploymentError):
                apply_policy_file(self.policy, "themis")
        self.assertEqual(read_policy_deployments(), [])

    def test_ledger_absent_returns_empty(self) -> None:
        self.assertEqual(read_policy_deployments(), [])


class PolicyCommandSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_run_and_file_are_mutually_exclusive(self) -> None:
        # argparse writes the usage/error to stderr before exiting; capture it so
        # the deliberate validation failure does not leak into the suite output.
        stderr = StringIO()
        with self.assertRaises(SystemExit), redirect_stderr(stderr):
            self.parser.parse_args(["policy", "--run", "X", "--file", "Y"])
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_one_source_is_required(self) -> None:
        stderr = StringIO()
        with self.assertRaises(SystemExit), redirect_stderr(stderr):
            self.parser.parse_args(["policy"])
        self.assertIn("one of the arguments", stderr.getvalue())

    def test_status_needs_no_other_argument(self) -> None:
        args = self.parser.parse_args(["policy", "--status"])
        self.assertTrue(args.status)


class PolicyStatusOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.ledger = Path(self.temporary_directory.name) / "ledger.jsonl"
        patcher = patch(
            "framework.cli.main._policy_ledger_path", return_value=self.ledger
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_status(self) -> str:
        buffer = StringIO()
        with redirect_stdout(buffer):
            main(["policy", "--status"])
        return buffer.getvalue()

    def test_reports_when_nothing_recorded(self) -> None:
        self.assertIn("No deployments recorded", self.run_status())

    def test_reports_recorded_deployment(self) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(
            json.dumps({
                "deployed_at": "2026-07-19T23:00:00+00:00",
                "target": "themis",
                "source": "run",
                "run_id": "20260719T230452981053Z",
                "policy_path": "artifacts/evidence/reference/tenant-restore-policy.nol",
                "policy_sha256": "0" * 64,
                "rule_count": 5000,
            }) + "\n",
            encoding="utf-8",
        )
        output = self.run_status()
        self.assertIn("20260719T230452981053Z", output)
        self.assertIn("5000", output)
        # The limitation must be stated in the output, not merely implied.
        self.assertIn("cannot report which policy is currently loaded", output)


if __name__ == "__main__":
    unittest.main()
