"""PDF text extractors that applicant tracking systems and resume parsers use.

Each `Extractor` turns a PDF into plain text the way some real-world pipeline
does. They fall into two families, which fail in different ways:

- Content-order readers (pypdf, PyMuPDF, PDFium, pdf.js, Tika by default)
  emit text in the order the PDF draws it.
- Layout-analyzing readers (pdfminer, pdfplumber, PDFBox sorted by position,
  pdftotext) regroup characters by where they sit on the page, so whitespace
  gaps can split a line into columns.

Expect the layout-analyzing readers to be the ones that break when the resume
content or template changes. Their failures come from page geometry, not from
the text itself: a new entry with a short date, or a wider gap somewhere, can
start one failing even though nothing looks wrong. Each such extractor carries a
`known_fragility` note, which the test prints on failure, describing what
broke it before and what fixed it. Before changing the template for one of
them, rerun all of them: fixes trade off. For example, filling gaps with
Unicode spaces such as U+2002 satisfies xpdf, but naive tokenizers then glue
the filler onto neighboring words.

Tools the project can provision itself are fetched on first use: the Tika jar
(pinned, checksum-verified) into tests/.tools/, and pdf.js via `npm ci` into
tests/pdfjs/node_modules/. Tools that must be installed system-wide (Java,
Node.js, pdftotext) are skipped with a reason when missing.
"""

import enum
import functools
import hashlib
import os
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pymupdf
import pypdf
import pypdfium2
import pytest
from pdfminer.high_level import extract_text as pdfminer_extract_text

TESTS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TESTS_DIR / ".tools"
PDFJS_DIR = TESTS_DIR / "pdfjs"


@dataclass(frozen=True)
class Extractor:
    name: str
    used_by: str
    extract: Callable[[Path], str]
    # Layouts this extractor has misread before, and what fixed them. Printed
    # with any failure, so whoever hits one starts from the likely cause.
    known_fragility: str | None = None


# Shared by pdftotext in both flavors.
SHORT_DATE_FRAGILITY = (
    "A short right-aligned date (e.g. \"2022\") with no line of its entry "
    "extending horizontally beneath it is read as a separate column and emitted "
    "after the entry's bullets. Spaces in the gap don't help: pdftotext ignores "
    "whitespace when finding columns. Fixed by a wider date (\"2021 – 2022\" "
    "instead of \"2022\"), or by a bullet long enough to reach under the date."
)


def run_for_stdout(command: list[str], **kwargs) -> str:
    return subprocess.run(command, capture_output=True, check=True, **kwargs).stdout.decode("utf-8")


def require_program(program: str, purpose: str) -> str:
    """The path to `program` on PATH; skips the test if it is missing."""
    path = shutil.which(program)
    if path is None:
        pytest.skip(f"{program} is not on PATH; it is needed for {purpose}")
    return path


# ---------------------------------------------------------------------------
# Python libraries
# ---------------------------------------------------------------------------


def extract_with_pypdf(pdf_path: Path) -> str:
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(pdf_path).pages)


def extract_with_pdfminer(pdf_path: Path) -> str:
    return pdfminer_extract_text(pdf_path)


def extract_with_pdfplumber(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as document:
        return "\n".join(page.extract_text() for page in document.pages)


def extract_with_pymupdf(pdf_path: Path) -> str:
    with pymupdf.open(pdf_path) as document:
        return "\n".join(page.get_text() for page in document)


def extract_with_pdfium(pdf_path: Path) -> str:
    document = pypdfium2.PdfDocument(pdf_path)
    try:
        return "\n".join(page.get_textpage().get_text_range() for page in document)
    finally:
        document.close()


# ---------------------------------------------------------------------------
# Apache Tika (PDFBox underneath)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PinnedDownload:
    url: str
    sha256: str

    @property
    def path(self) -> Path:
        return TOOLS_DIR / self.url.rsplit("/", 1)[1]


# Tika 3.x is the newest line that runs on Java 11 (4.x needs Java 17). 3.3.3
# bundles PDFBox 3.0.8. The checksum was verified against Maven Central's .sha1.
TIKA_APP_JAR = PinnedDownload(
    url="https://repo1.maven.org/maven2/org/apache/tika/tika-app/3.3.3/tika-app-3.3.3.jar",
    sha256="f29d4e0d2cff1fc32396f6ac5ce436dfc7b19f9303d3b899e1f56fde85711c96",
)
TIKA_SORT_BY_POSITION_CONFIG = TESTS_DIR / "tika-sort-by-position.xml"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(download: PinnedDownload) -> Path:
    """The downloaded file, fetching and verifying it on first use."""
    if download.path.exists() and sha256_of(download.path) == download.sha256:
        return download.path
    TOOLS_DIR.mkdir(exist_ok=True)
    partial_path = download.path.with_suffix(download.path.suffix + ".partial")
    urllib.request.urlretrieve(download.url, partial_path)
    actual_sha256 = sha256_of(partial_path)
    if actual_sha256 != download.sha256:
        partial_path.unlink()
        raise RuntimeError(
            f"{download.url} has SHA-256 {actual_sha256}, expected {download.sha256}"
        )
    partial_path.replace(download.path)
    return download.path


def extract_with_tika(pdf_path: Path, *, config_path: Path | None = None) -> str:
    java = require_program("java", "Apache Tika")
    config_args = [f"--config={config_path}"] if config_path is not None else []
    return run_for_stdout([
        java, "-jar", str(fetch(TIKA_APP_JAR)),
        *config_args, "--text", "--encoding=UTF-8", str(pdf_path),
    ])


def extract_with_tika_sorted(pdf_path: Path) -> str:
    return extract_with_tika(pdf_path, config_path=TIKA_SORT_BY_POSITION_CONFIG)


# ---------------------------------------------------------------------------
# pdf.js
# ---------------------------------------------------------------------------


def extract_with_pdfjs(pdf_path: Path) -> str:
    node = require_program("node", "pdf.js")
    if not (PDFJS_DIR / "node_modules" / "pdfjs-dist").exists():
        npm = require_program("npm", "installing pdf.js")
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=PDFJS_DIR, capture_output=True, check=True)
    return run_for_stdout([node, str(PDFJS_DIR / "extract_text.mjs"), str(pdf_path)])


# ---------------------------------------------------------------------------
# pdftotext: poppler's and xpdf's share a name but order text differently
# ---------------------------------------------------------------------------


class PdftotextFlavor(enum.Enum):
    POPPLER = "poppler"
    XPDF = "xpdf"


def pdftotext_flavor(executable: str) -> PdftotextFlavor:
    # Poppler descends from xpdf and credits it too, so only "Poppler" is decisive.
    version = subprocess.run([executable, "-v"], capture_output=True, text=True)
    banner = version.stdout + version.stderr
    return PdftotextFlavor.POPPLER if "Poppler" in banner else PdftotextFlavor.XPDF


@functools.cache
def find_pdftotext(flavor: PdftotextFlavor) -> str | None:
    """The first `pdftotext` of `flavor` on PATH, looking past others of the other flavor."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        executable = shutil.which("pdftotext", path=directory) if directory else None
        if executable is not None and pdftotext_flavor(executable) is flavor:
            return executable
    return None


def extract_with_pdftotext(pdf_path: Path, *, flavor: PdftotextFlavor, layout: bool) -> str:
    executable = find_pdftotext(flavor)
    if executable is None:
        pytest.skip(f"{flavor.value}'s pdftotext is not on PATH")
    layout_args = ["-layout"] if layout else []
    return run_for_stdout([executable, *layout_args, "-enc", "UTF-8", str(pdf_path), "-"])


def pdftotext_extractor(
    flavor: PdftotextFlavor, *, layout: bool, used_by: str, known_fragility: str | None = None,
) -> Extractor:
    mode = " -layout" if layout else ""
    return Extractor(
        f"{flavor.value} pdftotext{mode}",
        used_by,
        functools.partial(extract_with_pdftotext, flavor=flavor, layout=layout),
        known_fragility,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EXTRACTORS = [
    Extractor("pypdf", "Python pipelines, e.g. LangChain's default PDF loader in LLM-based screeners", extract_with_pypdf),
    Extractor(
        "pdfminer.six", "Python resume parsers (pyresparser and its forks)", extract_with_pdfminer,
        known_fragility=(
            "An empty gap between a title and its right-aligned dates splits the dates "
            "into their own text box, which lands mid-bullet or after the entry. "
            "resume.typ's title-line fills that gap with ASCII spaces to prevent this; "
            "if dates show up inside bullets, check that filler is still there."
        ),
    ),
    Extractor("pdfplumber", "Python resume parsers and data pipelines", extract_with_pdfplumber),
    Extractor("PyMuPDF", "Python pipelines and LLM document loaders", extract_with_pymupdf),
    Extractor("PDFium", "Chrome, and Python pipelines through pypdfium2", extract_with_pdfium),
    Extractor("Apache Tika", "Java/enterprise ATSes and search indexers (PDFBox, default settings)", extract_with_tika),
    Extractor("Apache Tika sorted", "PDFBox with sortByPosition, a common layout-aware setting", extract_with_tika_sorted),
    Extractor("pdf.js", "Firefox, and JavaScript resume parsers", extract_with_pdfjs),
    pdftotext_extractor(
        PdftotextFlavor.POPPLER, layout=False,
        used_by="Linux servers and many parser wrappers (poppler-utils)",
        known_fragility=(
            "The most layout-sensitive extractor here. (1) A gap wider than about "
            "0.15in between a bullet marker and its text (style.bullet-body-indent) "
            "makes it read every marker of an entry before any bullet text. "
            "(2) " + SHORT_DATE_FRAGILITY
        ),
    ),
    pdftotext_extractor(PdftotextFlavor.POPPLER, layout=True, used_by="parsers that want columns preserved (poppler-utils)"),
    pdftotext_extractor(
        PdftotextFlavor.XPDF, layout=False,
        used_by="xpdf command-line tools (e.g. bundled with Git for Windows)",
        known_fragility=SHORT_DATE_FRAGILITY,
    ),
]
