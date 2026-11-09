"""Builds the resume PDF and the README preview image, then tests the PDF.

    uv run build.py           # build both once, then run the tests
    uv run build.py --watch   # rebuild both on every save, and rerun the tests
                              # after each rebuild (Ctrl+C to stop)

The PDF uses your real contact block (contact.yaml, gitignored). The preview
image uses contact.example.yaml instead, so it can be committed without your
phone number and email.

The tests (tests/test_text_extraction.py) check that the PDF text extractors
used by applicant tracking systems read the resume correctly. A content edit
can break one without any visible change, so every build runs them.
"""

import argparse
import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
TEMPLATE = "resume.typ"
CONTENT_YAML = "resume.yaml"

RESUME_PDF = "Kumpf_Resume.pdf"
RESUME_CONTACT_YAML = "contact.yaml"

PREVIEW_PNG = "docs/resume_preview.png"
PREVIEW_CONTACT_YAML = "contact.example.yaml"
PREVIEW_RESOLUTION_PPI = 150

# How often watch mode checks whether Typst has written a new PDF.
WATCH_POLL_INTERVAL_S = 0.5


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


def require_pytest() -> None:
    if importlib.util.find_spec("pytest") is None:
        sys.exit(
            "pytest is not installed for this Python, so the resume can't be tested.\n"
            "Run the build through uv, which installs it: uv run build.py"
        )


def tests_pass() -> bool:
    """Runs the text-extraction tests, printing their results."""
    print("\ntesting how PDF text extractors read the resume...", flush=True)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=REPO_DIR)
    if result.returncode != 0:
        print(
            "\nTESTS FAILED: some PDF text extractors misread the resume (details above).\n"
            "The PDF was still built, but an applicant tracking system may parse it wrong.",
            flush=True,
        )
    return result.returncode == 0


def modification_time_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def build_once() -> None:
    for cmd in build_commands("compile"):
        subprocess.run(cmd, cwd=REPO_DIR, check=True)
        print(f"built {cmd[3]}")
    if not tests_pass():
        sys.exit(1)


def watch() -> None:
    """Runs `typst watch` for each output, and reruns the tests whenever the PDF is rewritten."""
    processes = [subprocess.Popen(cmd, cwd=REPO_DIR) for cmd in build_commands("watch")]
    resume_pdf = REPO_DIR / RESUME_PDF
    tested_pdf_mtime_ns = modification_time_ns(resume_pdf)
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(WATCH_POLL_INTERVAL_S)
            pdf_mtime_ns = modification_time_ns(resume_pdf)
            if pdf_mtime_ns is not None and pdf_mtime_ns != tested_pdf_mtime_ns:
                tested_pdf_mtime_ns = pdf_mtime_ns
                tests_pass()
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--watch", action="store_true", help="rebuild and retest on every save")
    args = parser.parse_args()

    if not (REPO_DIR / RESUME_CONTACT_YAML).exists():
        sys.exit(f"{RESUME_CONTACT_YAML} is missing: copy {PREVIEW_CONTACT_YAML} to it and fill it in")
    require_pytest()
    (REPO_DIR / PREVIEW_PNG).parent.mkdir(exist_ok=True)

    if args.watch:
        watch()
    else:
        build_once()


if __name__ == "__main__":
    main()
