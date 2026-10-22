"""Exercise the built subtree without the upstream checkout on its import path."""

from pathlib import Path
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    from agent.skill_utils import parse_frontmatter
except ImportError:
    parse_frontmatter = None

ROOT = Path(__file__).resolve().parents[1]


class HermesPackageTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "_workspace"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="hermes-package-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.checkout = Path(self.temp.name) / "checkout"
        self.checkout.mkdir()
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT
        ).decode().split("\0")
        for relative in filter(None, tracked):
            source = ROOT / relative
            if source.is_symlink():
                continue
            target = self.checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.run_command(["git", "init", "-q"], self.checkout)
        self.run_command(["git", "add", "."], self.checkout)
        builder = ROOT / "scripts/build_hermes_plugin.py"
        if builder.exists():
            shutil.copy2(builder, self.checkout / "scripts" / builder.name)
        if (ROOT / "hermes").exists():
            shutil.copytree(ROOT / "hermes", self.checkout / "hermes", dirs_exist_ok=True)

    def run_command(self, command, cwd, expected=0):
        env = {**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("CLAUDE_SKILL_DIR", None)
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=120,
            env=env,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def build(self):
        builder = self.checkout / "scripts/build_hermes_plugin.py"
        self.assertTrue(builder.is_file(), "The deterministic package builder is missing")
        self.run_command([sys.executable, str(builder)], self.checkout)
        # Copy only the deliverable, with spaces in its location and a foreign cwd.
        package = Path(self.temp.name) / "installed plugin"
        shutil.copytree(self.checkout / "plugins/humanize-korean", package)
        user = Path(self.temp.name) / "user work"
        user.mkdir()
        return package, user

    def script(self, package, user, name, *arguments, expected=0):
        return self.run_command(
            [sys.executable, str(package / "scripts" / name), *map(str, arguments)],
            user, expected,
        )

    def test_isolated_package_runs_shim_repairs_gates_and_strict_reassembly(self):
        package, user = self.build()
        original = "시민 120명이 도서관에서 책을 읽었다. 오늘도 같은 자리에서 차분하게 자료를 정리했다.\n"
        self.script(package, user, "prepare_monolith_input.py", "--text", original,
                    "--session-tag", "same-session")
        run = next((user / "_workspace").iterdir())
        metrics = json.loads((run / "00_metrics.json").read_text())
        self.assertIn(metrics["route_hint"], ("light", "standard", "heavy"))
        self.assertFalse((run / "00_metrics.error").exists())
        self.script(package, user, "prepare_monolith_input.py", "--run-dir", run, "--chunk")
        manifest = json.loads((run / "chunk_manifest.json").read_text())
        body = [c for c in manifest["chunks"] if not c["passthrough"]]
        self.assertEqual(len(body), 1)
        for chunk in body:
            (run / chunk["rewritten_file"]).write_text(
                original[chunk["start"]:chunk["end"]], encoding="utf-8"
            )
        self.script(package, user, "reassemble_chunks.py", "--run-dir", run, "--strict")
        final = run / "03_reassembled.md"
        self.assertEqual(final.read_text(), original)
        for repair in ("restore_modality.py", "strip_injected_commas.py"):
            self.script(package, user, repair, "--before", run / "01_input.txt",
                        "--after", final, "--out", final)
        gate = self.script(package, user, "verify_gates.py", "--before", run / "01_input.txt",
                           "--after", final, "--json")
        self.assertIn("[P3 golden]", gate.stdout)
        self.script(package, user, "verify_change_rate.py", "--before", run / "01_input.txt",
                    "--after", final)
        for candidate, exit_code in ((original.replace("120", "121"), 1), ("완전히 다른 내용이다.", 2)):
            with self.subTest(gate_exit=exit_code):
                final.write_text(candidate, encoding="utf-8")
                self.script(package, user, "verify_gates.py", "--before", run / "01_input.txt",
                            "--after", final, "--json", expected=exit_code)
        self.script(package, user, "verify_gates.py", "--before", run / "missing.txt",
                    "--after", final, expected=3)
        (run / body[0]["rewritten_file"]).write_text("짧다.", encoding="utf-8")
        self.script(package, user, "reassemble_chunks.py", "--run-dir", run, "--strict", expected=1)
        self.assertEqual((run / "01_input.txt").read_text(), original)
        self.script(package, user, "prepare_monolith_input.py", "--text", original,
                    "--session-tag", "same-session")
        self.assertEqual(len(list((user / "_workspace").iterdir())), 2)

    def test_check_rejects_upstream_drift_without_rewriting_package(self):
        self.build()
        builder = self.checkout / "scripts/build_hermes_plugin.py"
        command = [sys.executable, str(builder), "--check"]
        self.run_command(command, self.checkout)
        source = self.checkout / "scripts/prepare_monolith_input.py"
        shipped = self.checkout / "plugins/humanize-korean/scripts/prepare_monolith_input.py"
        before = shipped.read_bytes()
        source.write_bytes(source.read_bytes() + b"\n# Upstream correction\n")
        changed = self.run_command(command, self.checkout, expected=1)
        self.assertIn("scripts/prepare_monolith_input.py", changed.stdout)
        self.assertEqual(shipped.read_bytes(), before)
        self.run_command([sys.executable, str(builder)], self.checkout)
        self.run_command(command, self.checkout)
        self.assertEqual(shipped.read_bytes(), source.read_bytes())
        stale = self.checkout / "plugins/humanize-korean/skills/humanize/SKILL.md"
        stale.parent.mkdir()
        stale.write_text("Unwanted alias", encoding="utf-8")
        self.run_command(command, self.checkout, expected=1)
        self.run_command([sys.executable, str(builder)], self.checkout)
        self.assertFalse(stale.exists())
        self.run_command(command, self.checkout)

    def test_hermes_documented_allocation_preserves_leading_dashes(self):
        package, user = self.build()
        adapter = package / "hermes/skills/humanize-korean/SKILL.md"
        blocks = re.findall(r"```[^\n]*\n(.*?)```", adapter.read_text(), re.S)
        allocation = next(block for block in blocks if "--text" in block)
        original = "---\n제목\n---\n본문입니다."
        command = "\n".join([
            "PACKAGE_ROOT=" + shlex.quote(str(package)),
            "INPUT=" + shlex.quote(original),
            "GENRE=report",
            allocation,
        ])
        self.run_command(["sh", "-c", command], user)
        runs = list((user / "_workspace").glob("*/01_input.txt"))
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].read_text(), original)


    def test_host_manifest_selects_one_skill_and_documented_command_runs(self):
        package, user = self.build()
        self.assertTrue((package / ".claude-plugin/plugin.json").is_file(), "Host manifest is missing")
        manifest = json.loads((package / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(manifest["skills"], ["./skills/humanize-korean"])
        codex_manifest = package / ".codex-plugin/plugin.json"
        self.assertTrue(codex_manifest.is_file(), "Codex's string-path manifest is missing")
        codex = json.loads(codex_manifest.read_text())
        self.assertIsInstance(codex["skills"], str)
        self.assertEqual(codex["version"], manifest["version"])
        self.assertEqual(
            [p.parent.name for p in (package / codex["skills"]).rglob("SKILL.md")],
            ["humanize-korean"],
        )
        self.assertEqual(
            [p.name for p in (package / "skills").iterdir() if (p / "SKILL.md").exists()],
            ["humanize-korean"],
        )
        skill = package / manifest["skills"][0] / "SKILL.md"
        blocks = re.findall(r"```[^\n]*\n(.*?)```", skill.read_text(), re.S)
        command = next(block.strip() for block in blocks
                       if "prepare_monolith_input.py" in block and "--run-dir" in block
                       and "--diagnosis" not in block)
        self.assertEqual(shlex.split(command)[:7],
                         ["uv", "run", "--no-project", "--managed-python", "--python", ">=3.11", "python"])
        run = user / "_workspace" / "example"
        run.mkdir(parents=True)
        (run / "01_input.txt").write_text("도서관은 아침에 문을 연다.", encoding="utf-8")
        command = command.replace("_workspace/{run_id}", shlex.quote(str(run))).replace("{genre}", "essay")
        command = "SKILL_ROOT=" + shlex.quote(str(package)) + "\n" + command
        self.run_command(["sh", "-c", command], user)
        self.assertIn("route_hint", json.loads((run / "00_metrics.json").read_text()))
        codex_skill = package / codex["skills"] / "humanize-korean"
        launcher = codex_skill / "scripts/prepare_monolith_input.py"
        self.assertTrue(launcher.is_file(), "Codex must ship its own host entry point and runtime launchers")
        codex_blocks = re.findall(r"```[^\n]*\n(.*?)```", (codex_skill / "SKILL.md").read_text(), re.S)
        resolve = codex_blocks[0].replace("<이 SKILL.md가 있는 실제 디렉터리>", str(codex_skill))
        prepare = next(block for block in codex_blocks if "prepare_monolith_input.py" in block
                       and "--diagnosis" not in block and "--chunk" not in block)
        self.run_command(["sh", "-c", "\n".join([
            "RUN_DIR=" + shlex.quote(str(run)), "GENRE=essay", resolve, prepare,
        ])], user)
        self.run_command([
            sys.executable, str(codex_skill / "scripts/verify_gates.py"),
            "--before", str(run / "01_input.txt"), "--after", str(run / "01_input.txt"),
        ], user)

    @unittest.skipIf(parse_frontmatter is None, "Run with the Hermes runtime import path to check registration")
    def test_native_registration_preserves_parsed_metadata_and_role_paths(self):
        package, _ = self.build()
        self.assertTrue((package / "__init__.py").is_file(), "Native plugin entry point is missing")
        spec = importlib.util.spec_from_file_location("humanize_korean_plugin", package / "__init__.py")
        assert spec is not None and spec.loader is not None
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
        registrations = []

        class Context:
            def register_skill(self, *args):
                registrations.append(args)

        plugin.register(Context())
        self.assertEqual(len(registrations), 1)
        name, path, description, metadata = registrations[0]
        self.assertEqual(name, "humanize-korean")
        expected = package / "hermes/skills/humanize-korean/SKILL.md"
        self.assertEqual(path, expected)
        assert parse_frontmatter is not None
        frontmatter, _ = parse_frontmatter(expected.read_text())
        self.assertEqual((description, metadata), (frontmatter["description"], frontmatter))
        root = path.resolve().parents[3]
        references = root / "skills/humanize-korean/references"
        for role in (references / "roles").glob("*.md"):
            self.assertTrue(role.read_text(encoding="utf-8").strip())
        self.assertEqual(len(list((references / "roles").glob("*.md"))), 3)


if __name__ == "__main__":
    unittest.main()
