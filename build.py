"""Builds the resume PDF and the README preview image.

    python build.py           # build both once
    python build.py --watch   # rebuild both on every save (Ctrl+C to stop)

The PDF uses your real contact block (contact.yaml, gitignored). The preview
image uses contact.example.yaml instead, so it can be committed without your
phone number and email.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
TEMPLATE = "resume.typ"
CONTENT_YAML = "resume.yaml"

RESUME_PDF = "Kumpf_Resume.pdf"
RESUME_CONTACT_YAML = "contact.yaml"

PREVIEW_PNG = "docs/resume_preview.png"
PREVIEW_CONTACT_YAML = "contact.example.yaml"
PREVIEW_RESOLUTION_PPI = 150


def typst_args(mode: str, output: str, contact_yaml: str, *extra: str) -> list[str]:
    """A `typst compile` or `typst watch` command for one output file."""
    typst = shutil.which("typst")
    if typst is None:
        sys.exit("typst is not on PATH; install it from https://typst.app")
    return [
        typst, mode, TEMPLATE, output,
        "--input", f"data={CONTENT_YAML}",
        "--input", f"contact={contact_yaml}",
        *extra,
    ]


def build_commands(mode: str) -> list[list[str]]:
    return [
        typst_args(mode, RESUME_PDF, RESUME_CONTACT_YAML),
        typst_args(
            mode, PREVIEW_PNG, PREVIEW_CONTACT_YAML,
            "--pages", "1", "--ppi", str(PREVIEW_RESOLUTION_PPI),
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--watch", action="store_true", help="rebuild on every save")
    args = parser.parse_args()

    if not (REPO_DIR / RESUME_CONTACT_YAML).exists():
        sys.exit(f"{RESUME_CONTACT_YAML} is missing: copy {PREVIEW_CONTACT_YAML} to it and fill it in")
    (REPO_DIR / PREVIEW_PNG).parent.mkdir(exist_ok=True)

    if args.watch:
        processes = [subprocess.Popen(cmd, cwd=REPO_DIR) for cmd in build_commands("watch")]
        try:
            for process in processes:
                process.wait()
        except KeyboardInterrupt:
            for process in processes:
                process.terminate()
    else:
        for cmd in build_commands("compile"):
            subprocess.run(cmd, cwd=REPO_DIR, check=True)
            print(f"built {cmd[3]}")


if __name__ == "__main__":
    main()
