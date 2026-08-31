# Configuration

Phase 0 configuration is environment-based and validated by `meridian.settings.Settings`. Copy the
repository-root `.env.example` to an untracked `.env` file for local overrides. Real credentials must
come from that untracked file or a deployment secret store.

Later phases will add versioned, non-secret YAML files for model, retrieval, routing, and evaluation
defaults. Secret values and machine-specific paths must never appear in those files.
