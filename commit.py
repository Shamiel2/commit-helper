"""
Commit Helper
---------------------
Usage:
    python commit.py                     # auto-generate commit message
    python commit.py "My commit message" # use a custom commit message
    python commit.py --no-push           # commit but don't push
    python commit.py --dry-run           # show what would happen, don't commit

Workflow:
  1. Update requirements.txt via uv
  2. Stage all changes
  3. Generate (or use provided) commit message
  4. Commit & push to origin/<current-branch>
"""

import subprocess
import sys
import os
from datetime import datetime
import loguru


loguru.logger.info("Start".center(60, "-"))
# Force UTF-8 output on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def run(cmd, capture=True, check=True, cwd=None):
    """Run a command and return (stdout, stderr, returncode)."""
    # Accept string or list; split strings into args for cross-platform safety
    if isinstance(cmd, str):
        import shlex
        args = shlex.split(cmd)
    else:
        args = cmd
    result = subprocess.run(
        args,
        shell=False,
        capture_output=capture,
        text=True,
        cwd=cwd or REPO_ROOT,
    )
    if check and result.returncode != 0:
        loguru.logger.info(f"\n[ERROR] Command failed: {cmd}")
        if result.stderr:
            loguru.logger.error(result.stderr.strip())
        sys.exit(result.returncode)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


# ──────────────────────────────────────────────
# Step 1 — Update requirements.txt
# ──────────────────────────────────────────────
def update_requirements():
    loguru.logger.info("▸ Updating requirements.txt via uv...")
    _, err, code = run(
        "uv pip compile pyproject.toml -o requirements.txt",
        check=False,
    )
    if code != 0:
        loguru.logger.warning(f"  [WARN] uv pip compile failed ({err}). Skipping requirements update.")
    else:
        loguru.logger.info("  requirements.txt updated.")


# ──────────────────────────────────────────────
# Step 2 — Gather changes
# ──────────────────────────────────────────────
def get_status():
    out, _, _ = run("git status --short")
    return out


def get_diff_stat():
    out, _, _ = run("git diff --stat HEAD")
    return out


def get_changed_files():
    out, _, _ = run("git status --short")
    files = []
    for line in out.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip())
    return files


def get_current_branch():
    out, _, _ = run("git rev-parse --abbrev-ref HEAD")
    return out


# ──────────────────────────────────────────────
# Step 3 — Auto-generate commit message
# ──────────────────────────────────────────────
def categorize_files(files):
    categories = {
        "docs":    [],
        "tests":   [],
        "src":     [],
        "config":  [],
        "scripts": [],
        "other":   [],
    }
    for f in files:
        if f.startswith("docs/"):
            categories["docs"].append(f)
        elif f.startswith("tests/") or f.startswith("test_"):
            categories["tests"].append(f)
        elif f.startswith("src/"):
            categories["src"].append(f)
        elif f in ("pyproject.toml", "requirements.txt", "uv.lock",
                   ".gitignore", "setup.cfg", "setup.py", "CLAUDE.md"):
            categories["config"].append(f)
        elif f.startswith("scripts/") or f.endswith(".py") and "/" not in f:
            categories["scripts"].append(f)
        else:
            categories["other"].append(f)
    return {k: v for k, v in categories.items() if v}


def summarize_src_changes(src_files):
    """Group src changes by subsystem."""
    groups = {}
    for f in src_files:
        parts = f.split("/")
        # e.g. src/nodes/core/foo.py -> "nodes/core"
        subsystem = "/".join(parts[1:3]) if len(parts) >= 3 else parts[1] if len(parts) >= 2 else f
        groups.setdefault(subsystem, []).append(parts[-1])
    lines = []
    for subsystem, fnames in sorted(groups.items()):
        lines.append(f"  - {subsystem}: {', '.join(fnames)}")
    return lines


def auto_generate_message(files, branch):
    categories = categorize_files(files)
    total = len(files)

    if total == 0:
        return None

    # Title line
    date_str = datetime.now().strftime("%Y-%m-%d")
    branch_label = branch if branch not in ("main", "master") else ""
    title_parts = []

    if "src" in categories:
        n = len(categories["src"])
        title_parts.append(f"update {n} source file{'s' if n > 1 else ''}")
    if "docs" in categories:
        n = len(categories["docs"])
        title_parts.append(f"update {n} doc{'s' if n > 1 else ''}")
    if "tests" in categories:
        n = len(categories["tests"])
        title_parts.append(f"update {n} test{'s' if n > 1 else ''}")
    if "config" in categories:
        title_parts.append("update config")
    if not title_parts:
        title_parts.append(f"update {total} file{'s' if total > 1 else ''}")

    title = (f"{branch_label} — " if branch_label else "") + ", ".join(title_parts)
    title = title[0].upper() + title[1:]

    # Body
    body_lines = [f"Date: {date_str}", f"Branch: {branch}", ""]

    if "src" in categories:
        body_lines.append("Source changes:")
        body_lines.extend(summarize_src_changes(categories["src"]))
        body_lines.append("")

    if "docs" in categories:
        body_lines.append("Docs updated:")
        for f in categories["docs"][:10]:
            body_lines.append(f"  - {f}")
        if len(categories["docs"]) > 10:
            body_lines.append(f"  ... and {len(categories['docs']) - 10} more")
        body_lines.append("")

    if "tests" in categories:
        body_lines.append("Tests:")
        for f in categories["tests"]:
            body_lines.append(f"  - {f}")
        body_lines.append("")

    if "config" in categories:
        body_lines.append("Config / dependencies:")
        for f in categories["config"]:
            body_lines.append(f"  - {f}")
        body_lines.append("")

    if "scripts" in categories:
        body_lines.append("Scripts:")
        for f in categories["scripts"]:
            body_lines.append(f"  - {f}")
        body_lines.append("")

    if "other" in categories:
        body_lines.append("Other:")
        for f in categories["other"][:5]:
            body_lines.append(f"  - {f}")
        body_lines.append("")

    body_lines.append(f"Total files changed: {total}")

    return title + "\n\n" + "\n".join(body_lines).rstrip()


# ──────────────────────────────────────────────
# Step 4 — Stage, commit, push
# ──────────────────────────────────────────────
def stage_all():
    loguru.logger.info("▸ Staging all changes...")
    run("git add -A")


def commit(message):
    loguru.logger.info("▸ Committing...")
    # Write message to temp file to handle multi-line safely
    msg_file = os.path.join(REPO_ROOT, ".git", "_commit_msg_tmp")
    with open(msg_file, "w", encoding="utf-8") as f:
        f.write(message)
    run(f'git commit -F "{msg_file}"')
    os.remove(msg_file)


def push(branch):
    loguru.logger.info(f"▸ Pushing to origin/{branch}...")
    run(f"git push origin {branch}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    no_push = "--no-push" in args
    custom_msg = next((a for a in args if not a.startswith("--")), None)

    if dry_run:
        loguru.logger.info("[DRY RUN] No changes will be made.\n")

    # 1. Update requirements.txt
    if not dry_run:
        update_requirements()
    else:
        loguru.logger.info("▸ [skip] Update requirements.txt")

    # 2. Gather changes
    branch = get_current_branch()
    files = get_changed_files()
    status = get_status()

    loguru.logger.info(f"\n▸ Branch: {branch}")
    loguru.logger.info(f"▸ Changed files ({len(files)}):")
    if status:
        for line in status.splitlines():
            loguru.logger.info(f"   {line}")
    else:
        loguru.logger.info("   (no changes detected)")

    if not files:
        loguru.logger.info("\nNothing to commit. Exiting.")
        sys.exit(0)

    # 3. Determine commit message
    if custom_msg:
        message = custom_msg
        loguru.logger.info(f"\n▸ Using provided commit message: {message!r}")
    else:
        message = auto_generate_message(files, branch)
        loguru.logger.info(f"\n▸ Auto-generated commit message:\n{'─'*50}")
        loguru.logger.info(message)
        loguru.logger.info("─" * 50)

        if not dry_run:
            answer = input("\nUse this message? [Y/n/edit]: ").strip().lower()
            if answer == "n":
                loguru.logger.info("Aborted.")
                sys.exit(0)
            elif answer == "edit":
                loguru.logger.info("Enter your commit message (end with a blank line):")
                lines = []
                while True:
                    line = input()
                    if line == "":
                        break
                    lines.append(line)
                message = "\n".join(lines)

    if dry_run:
        loguru.logger.info("\n[DRY RUN] Would stage, commit, and push. Exiting.")
        sys.exit(0)

    # 4. Stage
    stage_all()

    # 5. Commit
    commit(message)

    # 6. Push
    if no_push:
        loguru.logger.info("▸ [skip] Push (--no-push flag set)")
    else:
        push(branch)

    loguru.logger.info("✓ Done!".center(60, "-"))


if __name__ == "__main__":
    main()
