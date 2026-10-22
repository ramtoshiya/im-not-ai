# Humanize Korean plugin

A self-contained package of the upstream Korean editing workflow for Hermes,
Claude Code, and Codex plugin loaders. Only `humanize-korean` is exposed. The
`humanize`, `humanize-scan`, and `humanize-redo` aliases are not installed.

Hermes registers `hermes/skills/humanize-korean/SKILL.md` as
`humanize-korean:humanize-korean`. The Claude and Codex compatibility manifests
select only `humanize-korean` from their respective `skills/` and `codex/skills/`
directories. The three Claude runtime agents are included. Hermes uses the
upstream role contracts through `delegate_task`, with
sequential execution when delegation is unavailable.

The light, standard, and heavy routes retain diagnosis, deterministic gates,
strict chunk reassembly, and finalization. This edits awkward Korean, not facts,
and does not remove or verify watermarks. Review warnings before publishing.

## Requirements

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and the host
agent separately. Runtime scripts use Python 3.11 or newer and only its standard
library. Commands use uv's managed Python and ignore unrelated project settings.
No installer or network access is needed by the builder.

## Build and check

From the fork checkout:

```sh
uv run --no-project --managed-python --python '>=3.11' python scripts/build_hermes_plugin.py
uv run --no-project --managed-python --python '>=3.11' python scripts/build_hermes_plugin.py --check
uv run --no-project --managed-python --python '>=3.11' python -m unittest discover -s tests -p test_hermes_package.py -v
```

Install or select the whole `plugins/humanize-korean` subtree, not an individual
skill folder. Native Hermes plugin checks can be run without enabling it:

```sh
hermes plugins doctor ./plugins/humanize-korean --ci
```

The builder reads upstream Git-tracked scripts, references, the canonical skill,
three runtime agents, and the MIT license. Those scripts and references remain
byte-identical. Codex receives its own upstream skill and launchers, with real
reference files instead of the source checkout's symlink. Packaged skill and
agent instructions use the uv
command above instead of bare `python3`. Hermes-specific source files live under
`hermes/`. Edit those sources, then rebuild. Do not edit generated package files.
`--check` reports missing, changed, or unexpected files without rewriting them.

Package tests build an isolated checkout, then run only the shipped subtree from
a different working directory. Native registration uses the real Hermes
frontmatter parser when the Hermes runtime is on the import path, otherwise that
one check is skipped. Tests do not run a model or evaluate editing quality.

User inputs and results go under the user's current directory in `_workspace/`,
never into this installed package. Keep that directory out of public commits.

Upstream author and MIT terms are in [LICENSE](LICENSE).
