"""
Bring the docs in step with the code, with an LLM on NCSA's Lumen.

    python scripts/docs_sync.py --style ../claude-config [--base <sha>] [--head <sha>]

It sends the model the writing rules and skills from Maharsh17/claude-config (--style),
the diff from --base (default the commit before --head) to --head, every docs page and the
code the pages describe. The model answers with the full text of each page that the change
made wrong or incomplete, and this script writes those pages into the checkout. It needs
LUMEN_API_KEY. .github/workflows/docs.yml runs it on every push to main, and
docs/guides/development.md#the-docs explains the flow.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LUMEN_URL = os.environ.get("LUMEN_URL", "https://lumen.ncsa.illinois.edu/v1")
MODEL = os.environ.get("LUMEN_MODEL", "glm-5.3")

# The pages the model may write. Anything else it sends back is ignored.
DOC_PATHS = ("README.md", "zensical.toml")
DOC_DIR = "docs/"
# The code it reads: tracked files under these paths, minus the noise below.
CODE_PATHS = ("app", "frontend/src", "scripts", ".github/workflows")
CODE_FILES = (
    "Makefile",
    "Dockerfile",
    "compose.yml",
    "compose.override.yml",
    "pyproject.toml",
    ".env.example",
    "PRODUCT.md",
)
CODE_SKIP = re.compile(r"(\.test\.|/test/|\.css$|\.scss$|\.png$|\.svg$|\.ico$)")
# The engine lives in a submodule, which `git ls-files` does not list. The docs quote its
# thresholds and scoring rules, so these two files go in too.
ENGINE_FILES = (
    "vendor/agent-lm-packages/learner_models/constants.py",
    "vendor/agent-lm-packages/learner_models/README.md",
)
# What the diff leaves out: the docs themselves, and lock files.
DIFF_SKIP = (":(exclude)docs", ":(exclude)README.md", ":(exclude)zensical.toml", ":(exclude)*lock*")
DIFF_MAX = 150_000  # characters; a bigger diff is cut, and the model is told so

FILE_BLOCK = re.compile(r"^<<<FILE (\S+)\n(.*?)\n>>>END$", re.S | re.M)

INSTRUCTIONS = """\
You maintain the documentation of lm-dashboard, the Learner Modeling Dashboard. It is an
Zensical site in docs/, with its nav in zensical.toml, plus the README.md on GitHub.
Readers are the researchers who use the board and the developers who run and change it.

Your job is to keep the docs true to the code. You get the code, the current docs and a
diff of what just changed. Find every statement in the docs that the code now
contradicts, every behavior the change added or removed that the docs should mention, and
every page that a reader would now find wrong or incomplete. Fix those, and nothing else.

Rules for the edit:
- The code is the truth. Never document something the code does not do, and never guess
  a number, a name, a default or a path. If you can't confirm it in the code, leave it out.
- Keep each page's structure, headings and wording wherever they are still right. Make the
  smallest edit that makes the page true. Don't rewrite a page for style alone.
- New pages are allowed only when a change adds a whole new area. Add each one to the nav
  in zensical.toml.
- Keep every link and anchor working. Anchors are the heading text, lowercased, with
  spaces as dashes and punctuation dropped. The site is built with `zensical build --strict`.
- Headings are in Title Case, as they are now.
- Write in the voice the style guide below describes. It is the author's own writing
  rules and skills, and every rule in it applies to every sentence you write. In
  particular, never use the em dash or the middle dot, never use a semicolon in prose,
  keep colons out of prose, and never write a bullet that opens with a bold label.

Answer format:
- For each file you change, send its full new text, exactly like this:
<<<FILE docs/concepts/write-path.md
...the whole file...
>>>END
- Send nothing outside those blocks except one short line per file saying what you fixed.
- If no page needs a change, answer with exactly NO_CHANGES.
"""


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def block(path, text):
    return f'<file path="{path}">\n{text}\n</file>\n'


def read_style(style_dir):
    """The author's writing rules and skills from claude-config: the global instructions,
    every skill the repo ships and the feedback memories."""
    root = Path(style_dir)
    paths = [root / "claude/CLAUDE.md"]
    paths += sorted(root.glob("claude/skills/*/SKILL.md"))
    paths += sorted(root.glob("memory/feedback_*.md"))
    found = [p for p in paths if p.is_file()]
    if not found:
        sys.exit(f"No claude-config files under {root}. Pass --style with its checkout.")
    return "".join(block(p.relative_to(root), p.read_text()) for p in found)


def tracked(head):
    return git("ls-tree", "-r", "--name-only", head).splitlines()


def read_docs(files):
    docs = [f for f in files if (f.startswith(DOC_DIR) and f.endswith(".md")) or f in DOC_PATHS]
    return "".join(block(f, (ROOT / f).read_text()) for f in docs)


def read_code(files):
    code = [
        f
        for f in files
        if (f in CODE_FILES or f.startswith(tuple(p + "/" for p in CODE_PATHS)))
        and not CODE_SKIP.search(f)
    ]
    code += [f for f in ENGINE_FILES if (ROOT / f).is_file()]
    return "".join(block(f, (ROOT / f).read_text()) for f in code)


def read_change(base, head):
    """The commit messages and the diff from base to head, without the docs and lock files."""
    log = git("log", "--format=- %s%n%b", f"{base}..{head}")
    # --submodule=diff shows what changed inside the engine, not only its new commit hash.
    diff = git("diff", "--submodule=diff", f"{base}..{head}", "--", ".", *DIFF_SKIP)
    if len(diff) > DIFF_MAX:
        diff = diff[:DIFF_MAX] + "\n[The diff was cut here. Read the code for the rest.]\n"
    return log, diff


def ask(system, user, model, key, attempts=3):
    """One chat completion on Lumen. It retries a failed call twice, since a long answer
    can time out on a busy server."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": 100_000,  # reasoning models think first, so leave room
        }
    ).encode()
    req = urllib.request.Request(
        f"{LUMEN_URL}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=1200) as resp:
                out = json.load(resp)
            choice = out["choices"][0]
            print(f"{model}: {out.get('usage')}, finish_reason={choice.get('finish_reason')}")
            if choice.get("finish_reason") == "length":
                print("The answer hit the token limit, so its last file may be cut off.")
            return choice["message"]["content"] or ""
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            if attempt == attempts:
                raise
            print(f"Lumen call {attempt} failed ({e}), trying again")
            time.sleep(20 * attempt)
    return ""


def apply(answer):
    """Write each file block in the answer. Returns the paths that changed."""
    changed = []
    for path, text in FILE_BLOCK.findall(answer):
        ok = path in DOC_PATHS or (path.startswith(DOC_DIR) and path.endswith(".md"))
        if not ok or ".." in path:
            print(f"Ignored {path}: the model may only write the docs.")
            continue
        # The author's rules forbid these two characters outright, so they never land.
        text = text.replace("—", "-").replace("·", "-").rstrip("\n") + "\n"
        target = ROOT / path
        if target.is_file() and target.read_text() == text:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        changed.append(path)
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--base", help="the commit before the change (default: --head's parent)")
    ap.add_argument("--head", default="HEAD", help="the commit to bring them up to")
    ap.add_argument("--style", required=True, help="a checkout of Maharsh17/claude-config")
    ap.add_argument("--model", default=MODEL, help=f"the Lumen model (default {MODEL})")
    opts = ap.parse_args(argv)

    key = os.environ.get("LUMEN_API_KEY")
    if not key:
        sys.exit("Set LUMEN_API_KEY.")

    # A push that creates the branch has no commit before it (its "before" is all zeros).
    base = opts.base
    if (
        not base
        or not base.strip("0")
        or subprocess.run(
            ["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=ROOT, capture_output=True
        ).returncode
    ):
        base = f"{opts.head}~1"

    files = tracked(opts.head)
    log, diff = read_change(base, opts.head)
    if not diff.strip():
        print("Only the docs changed, so there is nothing to check.")
        return
    task = (
        "These commits just landed on main.\n"
        f"<commits>\n{log}</commits>\n<diff>\n{diff}</diff>\n"
        "Bring the docs in step with this change."
    )

    system = f"{INSTRUCTIONS}\n<style_guide>\n{read_style(opts.style)}</style_guide>\n"
    user = f"<code>\n{read_code(files)}</code>\n<docs>\n{read_docs(files)}</docs>\n\n{task}\n"
    print(f"Prompt: about {(len(system) + len(user)) // 4:,} tokens")

    answer = ask(system, user, opts.model, key)
    if answer.strip() == "NO_CHANGES":
        print("The docs are current.")
        return
    changed = apply(answer)
    notes = FILE_BLOCK.sub("", answer).strip()
    if notes:
        print(notes)
    print(f"Changed {len(changed)} file(s): {', '.join(changed) or 'none'}")


if __name__ == "__main__":
    main()
