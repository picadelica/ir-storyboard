"""Ingest orchestrators (LLM Report + YouTube) over the four canonical channels.

Not fifth/sixth channels. Each pipeline parses an external artifact
(docx/md/pdf for LLM Report; YouTube URL for YouTube), extracts atomic
facts per matrix subsection, attributes them to one of the existing
channels (online_research / online_interview / archival /
offline_interview), and commits via matrix.add_fact / matrix.add_source.
"""
