"""Loader for .md / .txt files (Markdown exports from any LLM agent)."""
from __future__ import annotations

import re
from pathlib import Path

from ..ir import LLMReportIR, RawCitation, RawSection

_RE_BRACKET_N = re.compile(r"\[(\d+)\]")
_RE_URL = re.compile(r"https?://[^\s\]\)\>\"']+")
_RE_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")

_SOURCES_HINTS = ["источники", "sources", "references", "bibliography", "ссылки"]
_OPEN_Q_HINTS = ["open questions", "вопросы для интервью", "interview questions", "открытые вопросы"]
_SKIP_HINTS = ["выводы", "conclusions", "заключение", "conclusion", "summary", "итог"]


def load(path: Path) -> LLMReportIR:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    sections: list[RawSection] = []
    citations: dict[int, RawCitation] = {}
    open_questions: list[str] = []
    parser_notes: list[str] = []

    current_section: RawSection | None = None
    mode = "content"  # 'content' | 'sources' | 'open_questions' | 'skip'

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        hm = _RE_HEADING.match(stripped)
        if hm:
            level = len(hm.group(1))
            heading = hm.group(2).strip()
            heading_low = heading.lower()

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
                current_section = None
                parser_notes.append(f"Skipped section '{heading}' (meta/conclusions)")
                continue

            mode = "content"
            current_section = RawSection(heading=heading, level=level)
            sections.append(current_section)
            continue

        if mode == "skip":
            continue

        if mode == "sources":
            _parse_md_cite_line(stripped, citations)
            continue

        if mode == "open_questions":
            clean = re.sub(r"^[-•*\d.]+\s*", "", stripped).strip()
            if clean:
                open_questions.append(clean)
            continue

        # content
        if current_section is not None:
            # Skip fenced code blocks
            if stripped.startswith("```"):
                continue
            current_section.paragraphs.append(stripped)

    cite_list = [citations[k] for k in sorted(citations)]
    if not cite_list:
        cite_list = _fallback_extract(text)
        if cite_list:
            parser_notes.append("No structured citation block; extracted from inline markers")

    return LLMReportIR(
        source_filename=path.name,
        detected_agent="unknown",
        detected_cite_format="bracket_n" if _RE_BRACKET_N.search(text) else "unknown",
        sections=sections,
        citations=cite_list,
        open_questions=open_questions,
        parser_notes=parser_notes,
    )


def _parse_md_cite_line(text: str, out: dict[int, RawCitation]) -> None:
    # "[N] Title — Publisher — URL"
    m = re.match(r"^\[(\d+)\]\s*(.*?)(?:\s+[-–—]\s*|\s+)?(https?://\S+)?$", text)
    if m:
        cid = int(m.group(1))
        label = (m.group(2) or "").strip()
        url_raw = m.group(3) or ""
        if not url_raw:
            um = _RE_URL.search(text)
            url_raw = um.group(0) if um else ""
        out[cid] = RawCitation(
            cite_id=cid,
            raw_marker=f"[{cid}]",
            url=url_raw.rstrip(".,)>"),
            title=label[:200],
        )
        return

    # "N. Title URL"
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
