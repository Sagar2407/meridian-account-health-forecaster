# Meridian data boundary

All source records are synthetic. The supplied archive is retained locally at the repository root and
its unchanged extracted form is under `data/raw/meridian-account-health/`; both locations are ignored
by Git because generated raw data should not be duplicated in the public repository.

Phase 1 will preserve the supplied deterministic generator in `data/generator/` and create a central
loader that writes only sanitized derivatives. Runtime access must enforce:

```text
effective_cutoff = min(account.forecast_as_of_date, 2026-06-28)
```

Generated knowledge-base material, RAG indexes, and evaluation results belong in their named ignored
directories. Never edit raw files in place. See `docs/DATA_SAFETY.md` for the complete policy.
