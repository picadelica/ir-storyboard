"""Loader for .pdf files (Perplexity Pages, NotebookLM exports, etc.).

Uses pdfplumber for text extraction from the text layer.
No OCR — scanned PDFs are not supported (v3 scope).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..ir import LLMReportIR, RawCitation, RawSection

_RE_BRACKET_N = re.compile(r"\[(\d+)\]")
_RE_URL = re.compile(r"https?://[^\s\]\)\>\"']+")

_SOURCES_HINTS = ["источники", "sources", "references", "bibliography", "ссылки"]
_OPEN_Q_HINTS = ["open questions", "вопросы для интервью", "interview questions"]
_SKIP_HINTS = ["выводы", "conclusions", "заключение", "conclusion", "summary", "итог"]

_RE_ALLCAPS_HEADING = re.compile(r"^[A-ZА-ЯЁ\s&/]{4,60}$")


def load(path: Path) -> LLMReportIR:
    try:
        import pdfplumber
    except ImportError as e:
        raise ImportError(
            "pdfplumber is required for PDF loading. "
            "Add pdfplumber>=0.11 to requirements.txt"
        ) from e

    pages_text: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t)

    full_text = "\n".join(pages_text)
    lines = full_text.splitlines()

    sections: list[RawSection] = []
    citations: dict[int, RawCitation] = {}
    open_questions: list[str] = []
    parser_notes: list[str] = []

    current_section: RawSection | None = None
    mode = "content"

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        heading_low = stripped.lower()
        is_heading = _looks_like_heading(stripped)

        if is_heading:
            if any(h in heading_low for h in _SOURCES_HINTS):
                mode = "sources"
                current_section = None
                continue
            if any(h in heading_low for h in _OPEN_Q_HINTS):
                mode = "open_questions"
                current_section = None
                continue
            if any(h in heading_low for h in _SKIP_HINTS):
                mode = "skip"
                parser_notes.append(f"Skipped section '{stripped}' (meta/conclusions)")
                current_section = None
                continue

            mode = "content"
            current_section = RawSection(heading=stripped, level=1)
            sections.append(current_section)
            continue

        if mode == "skip":
            continue

        if mode == "sources":
            _parse_cite_line(stripped, citations)
            continue

        if mode == "open_questions":
            clean = re.sub(r"^[-•*\d.]+\s*", "", stripped).strip()
            if clean:
                open_questions.append(clean)
            continue

        if current_section is not None:
            current_section.paragraphs.append(stripped)

    cite_list = [citations[k] for k in sorted(citations)]
    if not cite_list:
        cite_list = _fallback_extract(full_text)
        if cite_list:
            parser_notes.append("No structured citation block; extracted inline markers")

    cite_format = "bracket_n" if _RE_BRACKET_N.search(full_text) else "unknown"

    return LLMReportIR(
        source_filename=path.name,
        detected_agent="unknown",
        detected_cite_format=cite_format,
        sections=sections,
        citations=cite_list,
        open_questions=open_questions,
        parser_notes=parser_notes,
    )


def _looks_like_heading(text: str) -> bool:
    """Heuristic: short line (≤80 chars), no period at end, possibly all-caps."""
    if len(text) > 80:
        return False
    if text.endswith(".") or text.endswith(","):
        return False
    if _RE_ALLCAPS_HEADING.match(text):
        return True
    # Title-case heuristic
    words = text.split()
    if 2 <= len(words) <= 10 and all(w[0].isupper() for w in words if w.isalpha()):
        return True
    return False


def _parse_cite_line(text: str, out: dict[int, RawCitation]) -> None:
    m = re.match(r"^\[(\d+)\]\s*(.*?)(?:\s+[-–—]\s*|\s+)?(https?://\S+)?$", text)
    if m:
        cid = int(m.group(1))
        label = (m.group(2) or "").strip()
        url_raw = m.group(3) or ""
        if not url_raw:
            um = _RE_URL.search(text)
            url_raw = um.group(0) if um else ""
        out[cid] = RawCitation(
            cite_id=cid, raw_marker=f"[{cid}]",
            url=url_raw.rstrip(".,)>"), title=label[:200],
        )
        return
    m2 = re.match(r"^(\d+)[.)]\s+(.+)$", text)
    if m2:
        cid = int(m2.group(1))
        rest = m2.group(2)
        um = _RE_URL.search(rest)
        url = um.group(0).rstrip(".,)>") if um else ""
        title = rest[: um.start()].strip() if um else rest[:200]
        out[cid] = RawCitation(cite_id=cid, raw_marker=str(cid), url=url, title=title[:200])


def _fallback_extract(text: str) -> list[RawCitation]:
    seen: set[int] = set()
    result = []
    for m in _RE_BRACKET_N.finditer(text):
        cid = int(m.group(1))
        if cid not in seen:
            seen.add(cid)
            result.append(RawCitation(cite_id=cid, raw_marker=m.group(0), url=""))
    return result
