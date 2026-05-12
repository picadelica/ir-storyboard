"""LLM Report Ingest — orchestrator over existing channels.

Not a fifth channel. Parses docx/md/pdf deep-research reports,
classifies each source URL to one of the four canonical channels,
extracts atomic facts per matrix subsection, and commits them
via matrix.add_fact / matrix.add_source.
"""
