"""Register the Hermes workflow without exposing the Claude entry point."""

from pathlib import Path

from agent.skill_utils import parse_frontmatter


def register(ctx):
    path = Path(__file__).resolve().parent / "hermes/skills/humanize-korean/SKILL.md"
    frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    ctx.register_skill("humanize-korean", path, frontmatter.get("description", ""), frontmatter)
