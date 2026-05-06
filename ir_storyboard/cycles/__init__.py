"""Three production cycles: weekly, event, quarterly.

Each cycle reads from the matrix and writes a markdown artifact ready for
NotebookLM (or any downstream production tool).
"""
from .weekly import run_weekly
from .event import run_event
from .quarterly import run_quarterly

__all__ = ["run_weekly", "run_event", "run_quarterly"]
