"""
Bring a repo's docs in step with its code, with an LLM on NCSA's Lumen.

    python path/to/docs_sync.py --style ../claude-config [--base <sha>] [--head <sha>]

Run it from the root of the repo whose docs it fixes. It reads that repo's settings from
.github/docs-bot.toml (--settings) and sends the model the writing rules and skills from
Maharsh17/claude-config (--style), the diff from --base (default the commit before --head) to
--head, every docs page and the code the pages describe. The model answers with the full text of
each page that the change made wrong or incomplete, and this script writes those pages into the
checkout. It needs LUMEN_API_KEY.

This is the one copy of the docs bot. .github/workflows/docs-bot.yml runs it for every repo
that calls that workflow (zany, atlas-invite, agent and this one), and
docs/guides/development.md#the-docs explains the flow.
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path.cwd()  # the repo whose docs it fixes
LUMEN_URL = os.environ.get("LUMEN_URL", "https://lumen.ncsa.illinois.edu/v1")
# The models to ask, in order. The next one answers when one fails. LUMEN_MODEL names one to use alone.
MODELS = (
    [os.environ["LUMEN_MODEL"]]
    if os.environ.get("LUMEN_MODEL")
    else ["glm-5.3", "glm", "deepseek-v4.1"]
)

# What each repo sets in its .github/docs-bot.toml, and the value when it says nothing.
SETTINGS = {
    # What these docs are and who reads them, and where a new page must be linked.
    "about": None,
    "new_page_rule": None,
    # The pages the model reads and may write (fnmatch globs, where * also crosses folders),
    # minus the protected ones. Anything else it sends back is ignored.
    "writable": None,
    "protected": [],
    # Repo files with doc rules of their own, added to the instructions (zany's AGENTS.md, say).
    "rule_files": [],
    # The code it reads: tracked files under code_paths and the code_files, minus code_skip.
    "code_paths": None,
    "code_files": [],
    "code_skip": r"\.(png|jpg|svg|ico)$",
    # Files that `git ls-tree` does not list but the docs quote, like a submodule's constants.
    "engine_files": [],
    # Pathspecs the diff leaves out: the docs themselves, and lock files.
    "diff_skip": [":(exclude)docs", ":(exclude)*.md", ":(exclude)*lock*"],
}
DIFF_MAX = 150_000  # characters; a bigger diff is cut, and the model is told so

FILE_BLOCK = re.compile(r"^<<<FILE (\S+)\n(.*?)\n>>>END$", re.S | re.M)

INSTRUCTIONS = """\
You maintain the documentation of {about}

Your job is to keep the docs true to the code. You get the code, the current docs and a
diff of what just changed. Find every statement in the docs that the code now
contradicts, every behavior the change added or removed that the docs should mention, and
every page that a reader would now find wrong or incomplete. Fix those, and nothing else.

Rules for the edit:
- The code is the truth. Never document something the code does not do, and never guess
  a number, a name, a default or a path. If you can't confirm it in the code, leave it out.
- Keep each page's structure, headings and wording wherever they are still right. Make the
  smallest edit that makes the page true. Don't rewrite a page for style alone.
- New pages are allowed only when a change adds a whole new area. {new_page_rule}
- Keep every link and anchor working. Anchors are GitHub's: the heading text, lowercased,
  with spaces as dashes and punctuation dropped. docs.inviteai.org is built with
  `zensical build --strict`, which fails on a broken link or anchor.
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


def load_settings(path):
    """The repo's settings, with the defaults filled in. An unknown or missing key stops the run,
    so a typo never quietly widens what the model may write."""
    with open(path, "rb") as f:
        found = tomllib.load(f)
    unknown = set(found) - set(SETTINGS)
    settings = SETTINGS | found
    missing = [k for k, v in settings.items() if v is None]
    if unknown or missing:
        sys.exit(f"{path}: unknown {sorted(unknown)}, missing {missing}")
    return settings


def tracked(head):
    return git("ls-tree", "-r", "--name-only", head).splitlines()


def writable(path, settings):
    """Whether the model may write this repo path. A path that normalizes to a different one
    (docs//changes/x.md, ../x, an absolute path) could slip past `protected`, so it is refused."""
    if posixpath.normpath(path) != path or path.startswith("/"):
        return False
    return any(fnmatch(path, g) for g in settings["writable"]) and not any(
        fnmatch(path, g) for g in settings["protected"]
    )


def read_docs(files, settings):
    return "".join(block(f, (ROOT / f).read_text()) for f in files if writable(f, settings))


def read_rules(settings):
    found = [f for f in settings["rule_files"] if (ROOT / f).is_file()]
    return "".join(block(f, (ROOT / f).read_text()) for f in found)


def read_code(files, settings):
    skip = re.compile(settings["code_skip"])
    folders = tuple(p + "/" for p in settings["code_paths"])
    code = [
        f
        for f in files
        if (f in settings["code_files"] or f.startswith(folders)) and not skip.search(f)
    ]
    code += [f for f in settings["engine_files"] if (ROOT / f).is_file()]
    return "".join(block(f, (ROOT / f).read_text()) for f in code)


def read_change(base, head, settings):
    """The commit messages and the diff from base to head, without the docs and lock files."""
    log = git("log", "--format=- %s%n%b", f"{base}..{head}")
    # --submodule=diff shows what changed inside the engine, not only its new commit hash.
    diff = git("diff", "--submodule=diff", f"{base}..{head}", "--", ".", *settings["diff_skip"])
    if len(diff) > DIFF_MAX:
        diff = diff[:DIFF_MAX] + "\n[The diff was cut here. Read the code for the rest.]\n"
    return log, diff


def ask(system, user, models, key):
    """One chat completion on Lumen, from the first model that answers. Lumen's gateway gives up
    on a request after about six minutes, which a busy model can hit on a long prompt, so a
    failed model is not tried again: the next one is."""
    for model in models:
        body = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 100_000,  # reasoning models think first, so leave room
            }
        ).encode()
        req = urllib.request.Request(
            f"{LUMEN_URL}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                out = json.load(resp)
            choice = out["choices"][0]
            print(f"{model}: {out.get('usage')}, finish_reason={choice.get('finish_reason')}")
            if choice.get("finish_reason") == "length":
                print("The answer hit the token limit, so its last file may be cut off.")
            return choice["message"]["content"] or ""
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            print(f"{model} failed ({e}), so the next model gets the question")
    raise RuntimeError(f"No Lumen model answered: {', '.join(models)}")


def apply(answer, settings):
    """Write each file block in the answer. Returns the paths that changed."""
    changed = []
    for path, text in FILE_BLOCK.findall(answer):
        if not writable(path, settings):
            print(f"Ignored {path}: the model may only write the docs.")
            continue
        # The author's rules forbid these two characters outright, so they never land.
        text = text.replace("\u2014", "-").replace("\u00b7", "-").rstrip("\n") + "\n"
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
    ap.add_argument(
        "--settings", default=".github/docs-bot.toml", help="the repo's settings for the bot"
    )
    ap.add_argument("--branch", default="main", help="the branch the commits landed on")
    ap.add_argument(
        "--model",
        action="append",
        help=f"a Lumen model to ask, in order (default {', '.join(MODELS)})",
    )
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

    settings = load_settings(ROOT / opts.settings)
    files = tracked(opts.head)
    log, diff = read_change(base, opts.head, settings)
    if not diff.strip():
        print("Only the docs changed, so there is nothing to check.")
        return
    task = (
        f"These commits just landed on {opts.branch}.\n"
        f"<commits>\n{log}</commits>\n<diff>\n{diff}</diff>\n"
        "Bring the docs in step with this change."
    )

    system = INSTRUCTIONS.format(
        about=settings["about"].strip(), new_page_rule=settings["new_page_rule"].strip()
    )
    system += f"\n<style_guide>\n{read_style(opts.style)}</style_guide>\n"
    if settings["rule_files"]:
        system += (
            "\nThis repo's own rules for its docs follow. They apply on top of everything above.\n"
            f"<repo_rules>\n{read_rules(settings)}</repo_rules>\n"
        )
    code, docs = read_code(files, settings), read_docs(files, settings)
    user = f"<code>\n{code}</code>\n<docs>\n{docs}</docs>\n\n{task}\n"
    print(f"Prompt: about {(len(system) + len(user)) // 4:,} tokens")

    answer = ask(system, user, opts.model or MODELS, key)
    if answer.strip() == "NO_CHANGES":
        print("The docs are current.")
        return
    changed = apply(answer, settings)
    notes = FILE_BLOCK.sub("", answer).strip()
    if notes:
        print(notes)
    print(f"Changed {len(changed)} file(s): {', '.join(changed) or 'none'}")
    # The workflow commits exactly these files, and nothing a check step left behind.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"changed={' '.join(changed)}\n")


if __name__ == "__main__":
    main()
