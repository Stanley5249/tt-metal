# Stanley5249/tt-metal agent rules

This is a fork. Branches, sync, release, and the patch list: fork/README.md. Commands: `just --list`.

## Branches

- `stable` and `main` are channels; `fork` is an orphan branch with only the fork-owned files that both channels merge. Because `fork` shares no files with a channel, edit it in its own worktree (`git worktree add .agents/worktrees/fork fork` if missing), commit there, then `git merge fork` on the channel. `just check` fails a channel whose fork-owned files differ from the fork commit it merged.
- Never merge a channel into `fork`, never rewrite pushed history or release tags, and take source fixes to the other channel with `git cherry-pick -x`.
- The `fork` branch has no `pixi.toml`, so recipes that also run there use `pixi run --script` and `pixi exec`, never the workspace.
- Keep one launcher level: a recipe composes stages by dependencies and never calls `just`, and a script starts an environment's binary with `sync.activated()` instead of nesting `pixi run`.

## Safety and approvals

- Ask before pushing, before `just publish`, before dispatching `fork-release`, and before changing GitHub workflows, releases, tags, or secrets.
- Use ttsim, never real hardware, unless hardware is authorized: the pixi environment sets `TT_METAL_SIMULATOR`, and a bare script outside it can open the card.
- Keep project dependencies inside pixi. Use CPU builds of torch.

## Common mistakes

- `uv run` in a channel's root syncs upstream's `pyproject.toml` and tries to build ttnn. Run fork scripts with `pixi run --script fork/scripts/<name>.py`.
- `TT_BUILD_JOBS` above about 10 can run a workstation out of memory during the unity build.
