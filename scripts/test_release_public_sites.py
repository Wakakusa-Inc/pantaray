"""Run with the agents development interpreter; PyYAML is installed there."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.load(
    (ROOT / ".github/workflows/release-public-sites.yml").read_text(),
    Loader=yaml.BaseLoader,
)
STEPS = {step["name"]: step for step in WORKFLOW["jobs"]["release"]["steps"]}


class PublicSiteReleaseTests(unittest.TestCase):
    def test_only_version_tags_on_main_reach_deployment(self):
        self.assertEqual(WORKFLOW["on"]["push"]["tags"], ["site/v*"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / "gh"
            gh.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_COMPARE_STATUS"\n')
            gh.chmod(0o700)
            for tag, status, valid in [
                ("site/v1.2.3", "identical", True),
                ("site/v1.2.3", "ahead", True),
                ("site/v1.2.3", "diverged", False),
                ("site/v1.2.3", "behind", False),
                ("site/vbad", "identical", False),
                ("web/v1.2.3", "identical", False),
            ]:
                with self.subTest(tag=tag, status=status):
                    result = subprocess.run(
                        ["bash", "-c", STEPS["Verify release tag is on main"]["run"]],
                        cwd=root,
                        env={
                            **os.environ,
                            "PATH": str(root) + os.pathsep + os.environ["PATH"],
                            "RELEASE_TAG": tag,
                            "RELEASE_SHA": "abc123",
                            "REPOSITORY": "Wakakusa-Inc/pantaray-cloud",
                            "TEST_COMPARE_STATUS": status,
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_both_sites_have_distinct_deployment_targets(self):
        for directory, target, site, public in [
            ("landing", "landing", "pantaray-alpha-landing", "."),
            ("website", "help", "pantaray-alpha-help", "dist"),
        ]:
            with self.subTest(directory=directory):
                deployment = STEPS[f"Deploy {target}"]
                self.assertNotIn("if", deployment)
                self.assertEqual(deployment["with"]["target"], target)
                self.assertEqual(deployment["with"]["entryPoint"], f"./{directory}")
                hosting = json.loads((ROOT / directory / "firebase.json").read_text())[
                    "hosting"
                ]
                targets = json.loads((ROOT / directory / ".firebaserc").read_text())[
                    "targets"
                ]
                self.assertEqual(hosting["target"], target)
                self.assertEqual(hosting["public"], public)
                self.assertEqual(targets["pantaray-alpha"]["hosting"][target], [site])


if __name__ == "__main__":
    unittest.main()
