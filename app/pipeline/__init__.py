"""The ingestion + inference daemon: poll prod, persist raw events, recompute
per-student state, and evaluate intervention triggers. Run via `python -m app.pipeline`.
"""
