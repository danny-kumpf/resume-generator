"""Checks that common PDF text extractors read the generated resume correctly.

Applicant tracking systems read the PDF's text layer, not the rendered page.
These tests compile each resume YAML with the Typst template. Each extractor
must recover every piece of text written in the YAML, unbroken, in the order a
person would read it. That catches missing glyph-to-Unicode mappings, mangled
ligatures or punctuation, words run together or split apart, and layout (such as
the right-aligned dates) that pulls text out of reading order.

If a content edit makes only a layout-analyzing extractor fail (poppler or xpdf
pdftotext, pdfminer), the cause is almost always geometry, not a bug: a short
date or a wide gap. That extractor's `known_fragility` note in extractors.py,
printed with the failure, says what to change. Out-of-order failures mean a
parser may pair a date or bullet with the wrong entry. "missing or garbled"
failures mean the text itself is unreadable, which is far more serious.
"""

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from extractors import EXTRACTORS

REPO_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_DIR / "resume.typ"
RESUME_YAML_PATHS = sorted(REPO_DIR.glob("resume*.yaml"))


def contact_yaml_path() -> Path:
    """The real contact block if present, else the committed example.

    contact.yaml is gitignored, so a fresh clone only has the example.
    """
    real_path = REPO_DIR / "contact.yaml"
    return real_path if real_path.exists() else REPO_DIR / "contact.example.yaml"


CONTACT_YAML_PATH = contact_yaml_path()


# ---------------------------------------------------------------------------
# Expected text, derived from the YAML
# ---------------------------------------------------------------------------

# Mirrors `inline-markup` in resume.typ: **bold**, [label](url), bare URLs.
INLINE_MARKUP = re.compile(
    r"\*\*(.+?)\*\*"
    r"|\[([^\]]+)\]\(([^)\s]+)\)"
    r"|(https?://[^\s,)]*[^\s,).])"
)


def visible_text(markup: str) -> str:
    """The text a reader sees once the template renders `markup`."""

    def render(match: re.Match) -> str:
        bold, label, _url, bare_url = match.groups()
        if bold is not None:
            return visible_text(bold)
        if label is not None:
            return label
        return bare_url

    return INLINE_MARKUP.sub(render, markup)


def bullet_texts(bullets: list) -> Iterator[str]:
    """Each bullet's text in reading order: a parent before its children."""
    for bullet in bullets:
        if isinstance(bullet, str):
            yield bullet
        else:
            yield bullet["text"]
            yield from bullet_texts(bullet["bullets"])


def reading_order_markup(resume: dict, contact_lines: list[str]) -> Iterator[str]:
    """Every text field in the resume, in the order resume.typ lays them out."""
    yield resume["name"]
    yield from contact_lines
    for section in resume["sections"]:
        yield section["title"].upper()
        for entry in section["entries"]:
            if "heading" in entry:
                yield entry["heading"]
                yield entry.get("dates", "")
            yield from bullet_texts(entry.get("bullets", []))
            for role in entry.get("roles", []):
                yield role["title"]
                yield role.get("dates", "")
                yield from bullet_texts(role.get("bullets", []))


def collapse_whitespace(text: str) -> str:
    """Joins wrapped lines and evens out spacing, which extractors render differently."""
    return " ".join(text.split())


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def expected_fragments(yaml_path: Path, contact_path: Path) -> list[str]:
    markup = reading_order_markup(load_yaml(yaml_path), load_yaml(contact_path))
    fragments = (collapse_whitespace(visible_text(m)) for m in markup)
    return [f for f in fragments if f]


# ---------------------------------------------------------------------------
# Fixtures and tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=RESUME_YAML_PATHS, ids=lambda p: p.name)
def resume_build(request, tmp_path_factory) -> tuple[Path, Path]:
    """Compiles one resume YAML; yields (yaml_path, pdf_path)."""
    yaml_path: Path = request.param
    typst = shutil.which("typst")
    if typst is None:
        pytest.fail("typst is not on PATH; it is needed to build the resume")
    pdf_path = tmp_path_factory.mktemp("build") / f"{yaml_path.stem}.pdf"
    subprocess.run(
        [
            typst, "compile", str(TEMPLATE_PATH), str(pdf_path),
            "--input", f"data={yaml_path.relative_to(REPO_DIR).as_posix()}",
            "--input", f"contact={CONTACT_YAML_PATH.relative_to(REPO_DIR).as_posix()}",
        ],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return yaml_path, pdf_path


@pytest.mark.parametrize("extractor", EXTRACTORS, ids=lambda e: e.name)
def test_extracted_text_matches_yaml_in_reading_order(resume_build, extractor):
    yaml_path, pdf_path = resume_build
    extracted = collapse_whitespace(extractor.extract(pdf_path))

    problems = []
    cursor = 0
    last_matched = None
    for fragment in expected_fragments(yaml_path, CONTACT_YAML_PATH):
        position = extracted.find(fragment, cursor)
        if position >= 0:
            cursor = position + len(fragment)
            last_matched = fragment
        elif fragment in extracted:
            problems.append(f"out of reading order: {fragment!r} comes before {last_matched!r}")
        else:
            problems.append(f"missing or garbled: {fragment!r}")

    fragility_note = (
        f"\n\nKnown fragility of {extractor.name}: {extractor.known_fragility}"
        if extractor.known_fragility is not None
        else ""
    )
    assert not problems, (
        f"{extractor.name} (used by {extractor.used_by}) misread {pdf_path.name}:\n  "
        + "\n  ".join(problems)
        + fragility_note
        + f"\n\nFull extracted text:\n{extracted}"
    )
