#!/usr/bin/env python3
"""Build the self-contained humanize-korean plugin from local upstream sources."""

from pathlib import Path
import argparse
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "humanize-korean"
RUNTIME = (
    "prepare_monolith_input.py", "reassemble_chunks.py", "verify_gates.py",
    "verify_change_rate.py", "restore_modality.py", "strip_injected_commas.py",
    "sanitize_text.py", "checks.py", "console.py",
)
ROLES = ("diagnostician", "monolith", "finalizer")
PYTHON = "uv run --no-project --managed-python --python '>=3.11' python"


def host_instructions(data):
    """Adapt documented commands, never executable upstream sources."""
    text = data.decode("utf-8").replace("python3", PYTHON)
    text = re.sub(r'(?<!["\w])(\$\{SKILL_ROOT\}/scripts/[\w]+\.py)', r'"\1"', text)
    return text.encode("utf-8")


def expected_files():
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0"))
    paths = {"LICENSE", "skills/humanize-korean/SKILL.md"}
    paths.update(f"scripts/{name}" for name in RUNTIME)
    paths.update(f"agents/humanize-{role}.md" for role in ROLES)
    paths.update(p for p in tracked if p.startswith("skills/humanize-korean/references/"))
    files = {}
    for relative in sorted(paths):
        if relative not in tracked:
            raise ValueError(f"Upstream source is not tracked: {relative}")
        data = (ROOT / relative).read_bytes()
        if relative == "skills/humanize-korean/SKILL.md" or relative.startswith("agents/"):
            data = host_instructions(data)
        files[relative] = data
    codex_root = "codex/skills/humanize-korean/"
    for relative in sorted(tracked):
        if relative.startswith(codex_root) and not (ROOT / relative).is_symlink():
            data = (ROOT / relative).read_bytes()
            files[relative] = host_instructions(data) if relative.endswith("SKILL.md") else data
    references = "skills/humanize-korean/references/"
    for relative, data in tuple(files.items()):
        if relative.startswith(references):
            files[codex_root + "references/" + relative.removeprefix(references)] = data
    for source, target in (
        ("hermes/__init__.py", "__init__.py"),
        ("hermes/plugin.yaml", "plugin.yaml"),
        ("hermes/README.md", "README.md"),
        ("hermes/skills/humanize-korean/SKILL.md", "hermes/skills/humanize-korean/SKILL.md"),
    ):
        files[target] = (ROOT / source).read_bytes()
    manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    manifest.update(
        version="2.3.2-hermes.2",
        skills=["./skills/humanize-korean"],
        repository="https://github.com/ramtoshiya/im-not-ai",
        homepage="https://github.com/ramtoshiya/im-not-ai",
    )
    files[".claude-plugin/plugin.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    codex = {**manifest, "skills": "./codex/skills/"}
    files[".codex-plugin/plugin.json"] = (json.dumps(codex, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report drift without writing files")
    args = parser.parse_args()
    expected = expected_files()
    actual = {
        p.relative_to(PACKAGE).as_posix(): p
        for p in PACKAGE.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    }
    changed = [name for name, data in expected.items()
               if name not in actual or actual[name].read_bytes() != data]
    stale = sorted(actual.keys() - expected.keys())
    if args.check:
        for name in sorted(changed):
            print(f"Drift: {name}")
        for name in stale:
            print(f"Unexpected: {name}")
        if changed or stale:
            return 1
        print("Package is up to date")
        return 0
    for name in stale:
        actual[name].unlink()
    for name, data in expected.items():
        target = PACKAGE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print(f"Built {PACKAGE.relative_to(ROOT)} ({len(expected)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
