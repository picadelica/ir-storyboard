"""Document loaders: docx / md / pdf → LLMReportIR."""
from .docx_loader import load as load_docx
from .md_loader import load as load_md
from .pdf_loader import load as load_pdf
from pathlib import Path
from ..ir import LLMReportIR


def load(path: Path) -> LLMReportIR:
    """Dispatch to the correct loader by file extension."""
    ext = path.suffix.lower()
    if ext == ".docx":
        return load_docx(path)
    elif ext in (".md", ".txt"):
        return load_md(path)
    elif ext == ".pdf":
        return load_pdf(path)
    else:
        raise ValueError(f"Unsupported format: {ext}. Expected .docx / .md / .txt / .pdf")
