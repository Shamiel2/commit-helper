# Commit Helper

A local Git commit helper that automates the full stage → commit → push workflow, with optional auto-generated commit messages.

## Features

- **Auto-generates commit messages** by categorizing changed files (source, docs, tests, config, scripts)
- **Updates `requirements.txt`** via `uv pip compile` before committing
- **Interactive review** — preview the auto-generated message and accept, abort, or edit it
- **Dry-run mode** — preview what would happen without making any changes
- **Custom message support** — pass your own message as a positional argument

## Requirements

- Python 3.8+
- [`uv`](https://github.com/astral-sh/uv) (for requirements compilation)
- [`loguru`](https://github.com/Delgan/loguru) (`pip install loguru`)
- Git available on `PATH`

## Usage

```bash
# Auto-generate a commit message, then prompt to confirm
python commit.py

# Use a custom commit message
python commit.py "Fix typo in README"

# Commit but skip pushing to remote
python commit.py --no-push

# Preview what would happen without making any changes
python commit.py --dry-run

# Combine flags
python commit.py "My message" --no-push
python commit.py --dry-run --no-push
```

## Workflow of the helper

1. **Update `requirements.txt`** — runs `uv pip compile pyproject.toml -o requirements.txt` (skipped on failure with a warning)
2. **Gather changes** — reads `git status` to list modified files and the current branch
3. **Determine commit message** — uses your provided message or auto-generates one:
   - Groups files by category: `src/`, `docs/`, `tests/`, config files, root-level scripts, and other
   - Builds a structured title + body including date, branch, and per-category file lists
   - Prompts: `[Y/n/edit]` — accept, abort, or enter a custom message interactively
4. **Stage all changes** — runs `git add -A`
5. **Commit** — writes the message to a temp file and runs `git commit -F`
6. **Push** — runs `git push origin <current-branch>` (skipped with `--no-push`)

## Auto-Generated Message Format

```
Update 3 source files, update config

Date: 2026-03-20
Branch: main

Source changes:
  - nodes/core: foo.py, bar.py
  - utils: helpers.py

Config / dependencies:
  - pyproject.toml
  - requirements.txt

Total files changed: 5
```

## File Categorization
These are the categories that the script looks at.

| Category  | Matches                                                   |
|-----------|-----------------------------------------------------------|
| `src`     | Files under `src/`                                        |
| `docs`    | Files under `docs/`                                       |
| `tests`   | Files under `tests/` or starting with `test_`            |
| `config`  | `pyproject.toml`, `requirements.txt`, `uv.lock`, `.gitignore`, `setup.cfg`, `setup.py`, `CLAUDE.md` |
| `scripts` | Files under `scripts/` or root-level `.py` files         |
| `other`   | Everything else                                           |

## Notes

- On Windows, stdout/stderr are forced to UTF-8 to handle unicode characters in file paths and log output.
- The commit message is written to `.git/_commit_msg_tmp` to safely handle multi-line messages, then deleted after the commit.
- If there are no changed files, the script exits cleanly with no action.
