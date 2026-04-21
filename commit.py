#!/usr/bin/env python3
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


def get_file_change_summary(filepath):
    """Get a short description of what changed in a file."""
    # Check if it's a new untracked file
    status_line, _, _ = run(f"git status --short -- {filepath}", check=False)
    if status_line.startswith("??") or status_line.startswith("A "):
        return "new file"
    if status_line.startswith(" D") or status_line.startswith("D "):
        return "deleted"
    if status_line.startswith("R"):
        return "renamed"

    # Get the diff for this file
    diff, _, code = run(f"git diff HEAD -- {filepath}", check=False)
    if code != 0 or not diff:
        # Try staged diff
        diff, _, _ = run(f"git diff --cached -- {filepath}", check=False)
    if not diff:
        return "modified"

    added = 0
    removed = 0
    change_hints = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
            stripped = line[1:].strip()
            # Detect common patterns
            if stripped.startswith("import ") or stripped.startswith("from "):
                if "import" not in change_hints:
                    change_hints.append("import")
            elif stripped.startswith("def "):
                fname = stripped.split("(")[0].replace("def ", "")
                change_hints.append(f"add {fname}()")
            elif stripped.startswith("class "):
                cname = stripped.split("(")[0].split(":")[0].replace("class ", "")
                change_hints.append(f"add class {cname}")
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1

    if change_hints:
        # Keep it short — max 3 hints
        summary = ", ".join(change_hints[:3])
        if len(change_hints) > 3:
            summary += f" +{len(change_hints) - 3} more"
        return summary

    if added and removed:
        return f"+{added}/-{removed} lines"
    elif added:
        return f"+{added} lines"
    elif removed:
        return f"-{removed} lines"
    return "modified"


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
        elif f.startswith("src/") or f.startswith("synapse/"):
            categories["src"].append(f)
        elif f in ("pyproject.toml", "requirements.txt", "uv.lock",
                   ".gitignore", "setup.cfg", "setup.py", "CLAUDE.md"):
            categories["config"].append(f)
        elif f.startswith("scripts/") or (f.endswith(".py") and "/" not in f):
            categories["scripts"].append(f)
        else:
            categories["other"].append(f)
    return {k: v for k, v in categories.items() if v}


def summarize_src_changes(src_files):
    """Group src changes by subsystem with per-file descriptions."""
    groups = {}
    for f in src_files:
        parts = f.split("/")
        subsystem = "/".join(parts[1:3]) if len(parts) >= 3 else parts[1] if len(parts) >= 2 else f
        desc = get_file_change_summary(f)
        groups.setdefault(subsystem, []).append((parts[-1], desc))
    lines = []
    for subsystem, file_descs in sorted(groups.items()):
        if len(file_descs) == 1:
            fname, desc = file_descs[0]
            lines.append(f"  - {subsystem}/{fname}: {desc}")
        else:
            lines.append(f"  - {subsystem}:")
            for fname, desc in file_descs:
                lines.append(f"      {fname}: {desc}")
    return lines


def _get_diff(filepath):
    """Get the diff for a file (unstaged or staged)."""
    diff, _, _ = run(f"git diff HEAD -- {filepath}", check=False)
    if not diff:
        diff, _, _ = run(f"git diff --cached -- {filepath}", check=False)
    return diff or ""


def _analyze_file_diff(filepath):
    """Analyse a single file's diff and return structured change info."""
    status_line, _, _ = run(f"git status --short -- {filepath}", check=False)
    if status_line.startswith("??") or status_line.startswith("A "):
        return {"action": "added", "file": filepath}
    if status_line.startswith(" D") or status_line.startswith("D "):
        return {"action": "deleted", "file": filepath}

    diff = _get_diff(filepath)
    info = {
        "action": "modified", "file": filepath,
        "added_funcs": [], "removed_funcs": [],
        "added_classes": [], "removed_classes": [],
        "added_imports": [], "removed_imports": [],
        "added_lines": 0, "removed_lines": 0,
        "keywords": set(),
    }
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            info["added_lines"] += 1
            s = line[1:].strip()
            if s.startswith("def "):
                info["added_funcs"].append(s.split("(")[0].replace("def ", ""))
            elif s.startswith("class "):
                info["added_classes"].append(s.split("(")[0].split(":")[0].replace("class ", ""))
            elif "import " in s:
                info["added_imports"].append(s)
            # Detect intent keywords
            sl = s.lower()
            for kw in ("fix", "refactor", "rename", "replace", "remove", "add", "update", "enable", "disable"):
                if kw in sl:
                    info["keywords"].add(kw)
        elif line.startswith("-") and not line.startswith("---"):
            info["removed_lines"] += 1
            s = line[1:].strip()
            if s.startswith("def "):
                info["removed_funcs"].append(s.split("(")[0].replace("def ", ""))
            elif s.startswith("class "):
                info["removed_classes"].append(s.split("(")[0].split(":")[0].replace("class ", ""))
            elif "import " in s:
                info["removed_imports"].append(s)
    return info


def _file_basename(filepath):
    """Get a readable short name: 'synapse/core/types.py' -> 'types.py'."""
    return filepath.replace("\\", "/").split("/")[-1]


def _subsystem_name(filepath):
    """Get the subsystem: 'synapse/widgets/preferences/preferences.py' -> 'widgets/preferences'."""
    parts = filepath.replace("\\", "/").split("/")
    if parts[0] in ("src", "synapse") and len(parts) >= 3:
        return "/".join(parts[1:3])
    elif len(parts) >= 2:
        return parts[0]
    return filepath


def generate_description(categories):
    """Build a human-readable description of the changes/updates made."""
    sentences = []

    # ── Source files ──
    if "src" in categories:
        file_infos = [_analyze_file_diff(f) for f in categories["src"]]

        added_files = [i for i in file_infos if i["action"] == "added"]
        deleted_files = [i for i in file_infos if i["action"] == "deleted"]
        modified_files = [i for i in file_infos if i["action"] == "modified"]

        if added_files:
            names = ", ".join(_file_basename(i["file"]) for i in added_files[:3])
            extra = f" and {len(added_files) - 3} more" if len(added_files) > 3 else ""
            sentences.append(f"Added {names}{extra}")

        if deleted_files:
            names = ", ".join(_file_basename(i["file"]) for i in deleted_files[:3])
            extra = f" and {len(deleted_files) - 3} more" if len(deleted_files) > 3 else ""
            sentences.append(f"Removed {names}{extra}")

        # Group modified files by subsystem for a cleaner description
        subsystems = {}
        for info in modified_files:
            sub = _subsystem_name(info["file"])
            subsystems.setdefault(sub, []).append(info)

        for sub, infos in sorted(subsystems.items()):
            parts = []
            all_funcs = []
            all_classes = []
            all_keywords = set()
            for info in infos:
                all_funcs.extend(info["added_funcs"])
                all_classes.extend(info["added_classes"])
                all_keywords.update(info["keywords"])

            if all_classes:
                names = ", ".join(all_classes[:3])
                parts.append(f"added class{'es' if len(all_classes) > 1 else ''} {names}")
            if all_funcs:
                names = ", ".join(all_funcs[:3])
                extra = f" +{len(all_funcs) - 3} more" if len(all_funcs) > 3 else ""
                parts.append(f"added {names}(){extra}")

            # Fall back to keyword-based description
            if not parts and all_keywords:
                parts.append(", ".join(sorted(all_keywords)[:3]))

            # Fall back to line counts
            if not parts:
                total_add = sum(i["added_lines"] for i in infos)
                total_rm = sum(i["removed_lines"] for i in infos)
                if total_add and total_rm:
                    parts.append(f"+{total_add}/-{total_rm} lines")
                elif total_add:
                    parts.append(f"+{total_add} lines")
                elif total_rm:
                    parts.append(f"-{total_rm} lines")
                else:
                    parts.append("minor changes")

            fnames = ", ".join(_file_basename(i["file"]) for i in infos[:2])
            if len(infos) > 2:
                fnames += f" +{len(infos) - 2} more"
            sentences.append(f"Updated {sub} ({fnames}): {'; '.join(parts)}")

    # ── Docs ──
    if "docs" in categories:
        n = len(categories["docs"])
        doc_names = [_file_basename(f).replace(".md", "") for f in categories["docs"][:3]]
        extra = f" +{n - 3} more" if n > 3 else ""
        sentences.append(f"Updated docs: {', '.join(doc_names)}{extra}")

    # ── Tests ──
    if "tests" in categories:
        n = len(categories["tests"])
        sentences.append(f"Updated {n} test file{'s' if n > 1 else ''}")

    # ── Config ──
    if "config" in categories:
        names = [_file_basename(f) for f in categories["config"]]
        sentences.append(f"Updated config: {', '.join(names)}")

    # ── Scripts ──
    if "scripts" in categories:
        for f in categories["scripts"]:
            info = _analyze_file_diff(f)
            name = _file_basename(f)
            if info["action"] == "added":
                sentences.append(f"Added script {name}")
            elif info["added_funcs"]:
                fns = ", ".join(info["added_funcs"][:3])
                sentences.append(f"Updated {name}: added {fns}()")
            else:
                sentences.append(f"Updated script {name}")

    if not sentences:
        return "General maintenance and updates."

    # Join with newlines, each prefixed with a bullet
    return "\n".join(f"  - {s}" for s in sentences)


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
    description = generate_description(categories)
    body_lines = [
        f"Date: {date_str}",
        f"Branch: {branch}",
        "",
        "Description:",
        description,
        "",
    ]

    if "src" in categories:
        body_lines.append("Source changes:")
        body_lines.extend(summarize_src_changes(categories["src"]))
        body_lines.append("")

    if "docs" in categories:
        body_lines.append("Docs updated:")
        for f in categories["docs"][:10]:
            desc = get_file_change_summary(f)
            body_lines.append(f"  - {f}: {desc}")
        if len(categories["docs"]) > 10:
            body_lines.append(f"  ... and {len(categories['docs']) - 10} more")
        body_lines.append("")

    if "tests" in categories:
        body_lines.append("Tests:")
        for f in categories["tests"]:
            desc = get_file_change_summary(f)
            body_lines.append(f"  - {f}: {desc}")
        body_lines.append("")

    if "config" in categories:
        body_lines.append("Config / dependencies:")
        for f in categories["config"]:
            desc = get_file_change_summary(f)
            body_lines.append(f"  - {f}: {desc}")
        body_lines.append("")

    if "scripts" in categories:
        body_lines.append("Scripts:")
        for f in categories["scripts"]:
            desc = get_file_change_summary(f)
            body_lines.append(f"  - {f}: {desc}")
        body_lines.append("")

    if "other" in categories:
        body_lines.append("Other:")
        for f in categories["other"][:5]:
            desc = get_file_change_summary(f)
            body_lines.append(f"  - {f}: {desc}")
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
