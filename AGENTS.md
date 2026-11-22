# Stanley5249/tt-metal agent rules

This is a fork. Branches, sync, release, and the patch list: fork/README.md. Commands: `just --list`.

## Branches

- `stable` and `main` are channels; `fork` is an orphan branch with only the fork-owned files that both channels merge. Commit fork-owned changes on `fork` in `.agents/worktrees/fork`, then `git merge fork` on the channel. `just check` fails a channel whose fork-owned files differ from the fork commit it merged.
- Never merge a channel into `fork`, never rewrite pushed history or release tags, and take source fixes to the other channel with `git cherry-pick -x`.
- Recipes on the `fork` worktree must not call `pixi run`: it has no `pixi.toml`.
- Keep one launcher level: a recipe composes stages by dependencies and never calls `just`, and a script starts an environment's binary with `sync.activated()` instead of nesting `pixi run`.

## Safety and approvals

- Ask before pushing, before `just publish`, before dispatching `fork-release`, and before changing GitHub workflows, releases, tags, or secrets.
- Use ttsim, never real hardware, unless hardware is authorized: the pixi environment sets `TT_METAL_SIMULATOR`, and a bare script outside it can open the card.
- Keep project dependencies inside pixi. Use CPU builds of torch.

## Common mistakes

- `uv run` in a channel's root syncs upstream's `pyproject.toml` and tries to build ttnn. Run fork scripts as `uv run fork/scripts/<name>.py`, whose PEP 723 header ignores the project, and anything else with `uv run --no-project`.
- `TT_BUILD_JOBS` above about 10 can run a workstation out of memory during the unity build.
- A Tracy capture leaves its viewer on ports 8080 and 8081. Stop it by its PID, never with `pkill -f`.
