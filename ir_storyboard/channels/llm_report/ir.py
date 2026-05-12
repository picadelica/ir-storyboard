"""Canonical IR (Intermediate Representation) for LLM report documents.

All loaders (docx / md / pdf) produce a single LLMReportIR instance.
No LLM calls happen at this stage — pure structural parsing.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawCitation:
    cite_id: int           # 1..N as numbered by the LLM
    raw_marker: str        # original text: '[1]', '(Source 1)', '¹', ...
    url: str               # extracted URL, or "" if none found
    title: str = ""
    publisher: str = ""    # from URL hostname or inline label


@dataclass
class RawSection:
    heading: str                           # e.g. 'Обзор', 'Investments & Financing'
    level: int                             # 1 = H1, 2 = H2
    paragraphs: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)


@dataclass
class LLMReportIR:
    source_filename: str
    detected_agent: str | None            # 'chatgpt-deep-research' / 'claude' / 'perplexity' / 'gemini' / 'unknown'
    detected_cite_format: str             # 'bracket_n' / 'paren_source_n' / 'superscript' / 'unknown'
    sections: list[RawSection] = field(default_factory=list)
    citations: list[RawCitation] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    parser_notes: list[str] = field(default_factory=list)
