#!/usr/bin/env python3
"""Regression checks for app selection and CLI orchestration; no image builds."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("selector", ROOT / "scripts/select-changed-apps.py")
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)
APPS = list(selector.TARGET_PACKAGES)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "light-example-rs"
        self.fabric = self.root.parent / "light-fabric"
        packages = []
        nodes = []
        for name in APPS + ["light-axum", "light-client"]:
            directory = (self.root / "apps" / name if name in APPS
                         else self.fabric / "crates" / name)
            (directory / "src").mkdir(parents=True)
            packages.append({"id": name, "name": name, "source": None,
                             "manifest_path": str(directory / "Cargo.toml")})
            dependencies = (["light-client"] if name == APPS[0] else
                            ["light-axum"] if name in APPS[1:] else [])
            nodes.append({"id": name, "deps": [{"pkg": x} for x in dependencies]})
        self.metadata = {"packages": packages, "resolve": {"nodes": nodes}}

    def select(self, dirty, requested=None):
        with contextlib.redirect_stderr(io.StringIO()):
            return selector.select_images(self.root, set(dirty), self.metadata,
                                          set(requested or []))

    def test_app_config_selects_only_its_image(self):
        self.assertEqual(self.select([self.root / "apps" / APPS[1] / "config/server.yml"]), [APPS[1]])

    def test_sibling_dependency_selects_only_consumers(self):
        self.assertEqual(self.select([self.fabric / "crates/light-client/src/lib.rs"]), [APPS[0]])
        self.assertEqual(self.select([self.fabric / "crates/light-axum/src/lib.rs"]), APPS[1:])

    def test_transitive_dependency(self):
        self.metadata["resolve"]["nodes"][-2]["deps"] = [{"pkg": "light-client"}]
        self.assertEqual(self.select([self.fabric / "crates/light-client/src/lib.rs"]), APPS)

    def test_build_wide_inputs_and_candidate_restriction(self):
        for path in [self.root / "Cargo.lock", self.fabric / "Cargo.toml",
                     self.root / "docker/Dockerfile", self.root / "docker/Dockerfile.dockerignore"]:
            self.assertEqual(self.select([path]), APPS)
            self.assertEqual(self.select([path], [APPS[2]]), [APPS[2]])

    def test_docs_do_not_select_images(self):
        self.assertEqual(self.select([self.root / "README.md", self.fabric / "docs/src/page.md"]), [])

    def test_shared_contract_readers_and_unknown_fallback(self):
        source = self.root / "apps" / APPS[0] / "src/main.rs"
        source.write_text('include_str!("../../../../light-fabric/contracts/workflow/spec.json");')
        self.assertEqual(self.select([self.fabric / "contracts/workflow/spec.json"]), [APPS[0]])
        self.assertEqual(self.select([self.fabric / "contracts/new/spec.json"]), APPS)

    def test_incomplete_graph_fails_closed(self):
        self.metadata["resolve"] = None
        with self.assertRaises(selector.SelectionError):
            self.select([self.root / "apps" / APPS[0] / "src/main.rs"])

    def test_git_staged_unstaged_untracked_and_deleted(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        def git(*args):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)
        for name in ["staged", "unstaged", "deleted"]:
            (self.root / name).write_text("before")
        git("add", ".")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        (self.root / "staged").write_text("after")
        git("add", "staged")
        (self.root / "unstaged").write_text("after")
        (self.root / "deleted").unlink()
        (self.root / "untracked").write_text("new")
        self.assertEqual(selector.changed_paths(self.root),
                         {self.root / name for name in ["staged", "unstaged", "deleted", "untracked"]})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.log = directory / "calls.jsonl"
        docker = directory / "docker"
        docker.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["TEST_DOCKER_LOG"], "a") as f:
    f.write(json.dumps({"args":sys.argv[1:], "buildkit":os.environ.get("DOCKER_BUILDKIT")})+"\\n")
if sys.argv[1] == "build" and os.environ.get("TEST_FAIL_APP") and any(
    x == "APP_NAME=" + os.environ["TEST_FAIL_APP"] for x in sys.argv):
    sys.exit(1)
''')
        docker.chmod(0o755)
        self.env = {**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                    "TEST_DOCKER_LOG": str(self.log)}

    def run_cli(self, *args):
        result = subprocess.run(["bash", str(ROOT / "build.sh"), *args], env=self.env,
                                capture_output=True, text=True, cwd="/tmp")
        calls = [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    def test_all_builds_finish_before_first_push(self):
        result, calls = self.run_cli("test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c["args"][0] for c in calls], ["build"] * 4 + ["push"] * 8)
        self.assertTrue(all(c["buildkit"] == "1" for c in calls[:4]))
        self.assertTrue(all("CARGO_CACHE_ID=warm" in c["args"] for c in calls[:4]))

    def test_failed_later_build_never_publishes(self):
        self.env["TEST_FAIL_APP"] = APPS[2]
        result, calls = self.run_cli("test")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c["args"][0] for c in calls], ["build"] * 3)

    def test_local_single_app_namespace_and_skip_latest(self):
        result, calls = self.run_cli("test", "--local", "--app", APPS[1],
                                     "--image-org", "custom", "--skip-latest")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn("custom/" + APPS[1] + ":test", calls[0]["args"])
        self.assertFalse(any(x.endswith(":latest") for x in calls[0]["args"]))

    def test_cold_cache_cleanup_is_scoped_even_on_failure(self):
        self.env["TEST_FAIL_APP"] = APPS[1]
        result, calls = self.run_cli("test", "--no-cache")
        self.assertNotEqual(result.returncode, 0)
        builds = calls[:2]
        ids = [next(x.split("=", 1)[1] for x in c["args"] if x.startswith("CARGO_CACHE_ID=")) for c in builds]
        self.assertNotEqual(ids[0], ids[1])
        self.assertTrue(all("--no-cache" in c["args"] and x.startswith("cold-") for c, x in zip(builds, ids)))
        self.assertEqual(calls[-1]["args"][:2], ["builder", "prune"])
        prefix = calls[-1]["args"][-1].removeprefix("description~=")
        self.assertTrue(all(x.startswith(prefix) for x in ids))
        self.assertFalse(any(c["args"][0] == "push" for c in calls))

    def test_unknown_app_does_not_invoke_docker(self):
        result, calls = self.run_cli("test", "--app", "unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
