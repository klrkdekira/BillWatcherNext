# Retrieval and answer evaluations

HANDOFF section 13 forbids shipping RAG until a small, versioned Malay/English evaluation set
covers identifier lookup, status questions, cross-chamber timelines, amendments,
superseded-document cases, no-answer cases, and citation correctness.

`retrieval-v1.json` is that set. It is versioned: change a case and bump `set_version`, because
scores from different versions are not comparable.

Run it with:

```
make evaluate                      # dry summary against the configured providers
uv run billwatcher evaluate --json # machine-readable output
```

The runner builds a disposable in-memory corpus from `corpus.json`, chunks and embeds it with
the configured embedding provider, and scores retrieval and citation behaviour. It never touches
the production database and never contacts Parliament.

## What the gate means

The development `deterministic` embedding provider is a hashed bag-of-words projection with no
semantic understanding. It exists so the pipeline can be exercised offline; it will not clear the
thresholds below and is rejected in production configuration.

Before `SEMANTIC_SEARCH_ENABLED=true` or `RAG_ENABLED=true` reaches production, run this suite
against the real configured model and record the result, the date, and the model ID in the manual
gate log in `docs/status.md`. The release thresholds are:

| Metric | Threshold |
| --- | --- |
| `recall_at_5` over cases with an expected bill | at least 0.80 |
| `no_answer_correct` over the no-evidence cases | 1.00 |
| `citation_validity` (every citation names a supplied chunk) | 1.00 |
| `version_pinned` (every citation names a document version and retrieval date) | 1.00 |
