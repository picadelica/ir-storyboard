"""Loader for .md / .txt files (Markdown exports from any LLM agent)."""
from __future__ import annotations

import re
from pathlib import Path

from ..ir import LLMReportIR, RawCitation, RawSection

_RE_BRACKET_N = re.compile(r"\[(\d+)\]")
_RE_URL = re.compile(r"https?://[^\s\]\)\>\"']+")
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")  # markdown допускает до 6 уровней (LLM даёт ####)
# Gemini/Perplexity inline links: [title](url) or [^N]: url
_RE_INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")

_SOURCES_HINTS = ["источники", "sources", "references", "bibliography", "ссылки"]
_OPEN_Q_HINTS = ["open questions", "вопросы для интервью", "interview questions", "открытые вопросы"]
_SKIP_HINTS = ["выводы", "conclusions", "заключение", "conclusion", "summary", "итог"]


def _special_mode(heading_low: str) -> str | None:
    """Метка секции по её тексту (нижний регистр): sources / open_questions / skip / None."""
    if any(h in heading_low for h in _SOURCES_HINTS):
        return "sources"
    if any(h in heading_low for h in _OPEN_Q_HINTS):
        return "open_questions"
    if any(h in heading_low for h in _SKIP_HINTS):
        return "skip"
    return None


def _pseudo_heading_label(stripped: str) -> str | None:
    """LLM часто оформляет секцию не markdown-заголовком, а жирным (`**Sources**`) или
    строкой с двоеточием (`Источники:`). Распознаём такую строку-ярлык (короткую,
    самостоятельную) → её текст; иначе None. Только для СПЕЦ-секций (проверяет вызывающий)."""
    s = stripped
    is_bold = (s.startswith("**") and s.endswith("**") and len(s) > 4) or (
        s.startswith("__") and s.endswith("__") and len(s) > 4)
    core = s.strip("*_").strip()
    has_colon = core.endswith(":")
    if not (is_bold or has_colon):
        return None
    core = core.rstrip(":").strip()
    # ярлык-заголовок: короткий, без внутренней пунктуации предложения
    if not core or len(core) > 40 or "." in core:
        return None
    return core


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
            special = _special_mode(heading.lower())
            if special is not None:
                mode = special
                current_section = None
                if special == "skip":
                    parser_notes.append(f"Skipped section '{heading}' (meta/conclusions)")
                continue

            mode = "content"
            current_section = RawSection(heading=heading, level=level)
            sections.append(current_section)
            continue

        # LLM оформил спец-секцию не заголовком, а жирным/строкой с двоеточием
        if mode != "sources":  # уже в источниках — строки разбираем как цитаты, не как ярлык
            label = _pseudo_heading_label(stripped)
            if label is not None:
                special = _special_mode(label.lower())
                if special is not None:
                    mode = special
                    current_section = None
                    if special == "skip":
                        parser_notes.append(f"Skipped section '{label}' (meta/conclusions)")
                    else:
                        parser_notes.append(
                            f"Секция '{label}' распознана без markdown-заголовка "
                            f"({'жирным' if stripped.startswith('*') or stripped.startswith('_') else 'строкой с двоеточием'})")
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
        # Try inline links first (Gemini / Perplexity format)
        cite_list = _extract_inline_links(text)
        if cite_list:
            parser_notes.append("No structured citation block; extracted inline [text](url) links")
        else:
            cite_list = _fallback_extract(text)
            if cite_list:
                parser_notes.append("No structured citation block; extracted [N] markers only (no URLs)")

    cite_format = "bracket_n" if _RE_BRACKET_N.search(text) else (
        "inline_links" if _RE_INLINE_LINK.search(text) else "unknown"
    )
    return LLMReportIR(
        source_filename=path.name,
        detected_agent="unknown",
        detected_cite_format=cite_format,
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


def _extract_inline_links(text: str) -> list[RawCitation]:
    """Extract [title](url) inline Markdown links (Gemini / Perplexity format)."""
    seen_urls: dict[str, int] = {}
    result = []
    for m in _RE_INLINE_LINK.finditer(text):
        title = m.group(1).strip()
        url = m.group(2).rstrip(".,)>")
        if url in seen_urls:
            continue
        cid = len(result) + 1
        seen_urls[url] = cid
        result.append(RawCitation(
            cite_id=cid,
            raw_marker=m.group(0)[:80],
            url=url,
            title=title[:200],
        ))
    return result


def _fallback_extract(text: str) -> list[RawCitation]:
    """Last resort: collect unique [N] markers without URLs."""
    seen: set[int] = set()
    result = []
    for m in _RE_BRACKET_N.finditer(text):
        cid = int(m.group(1))
        if cid not in seen:
            seen.add(cid)
            result.append(RawCitation(cite_id=cid, raw_marker=m.group(0), url=""))
    return result
