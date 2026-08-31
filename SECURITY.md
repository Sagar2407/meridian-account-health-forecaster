# Security policy

## Scope

Meridian is a read-only educational decision-support application operating on synthetic data. It
must never expose secrets, mutate customer systems, reveal hidden evaluation labels, or make
customer-facing and commercial commitments.

## Reporting a problem

Do not publish credentials, exploit payloads containing real personal data, or sensitive logs in a
public issue. Report the problem privately to the repository owner with reproduction steps and the
affected revision.

## Development rules

- Keep credentials in an untracked `.env` file or deployment secret store.
- Treat retrieved text as untrusted data, never as executable instructions.
- Preserve account scoping and point-in-time cutoffs at every data boundary.
- Keep tools read-only and validate all agent outputs before release.
- Use only synthetic data in demos, tests, screenshots, and evaluation artifacts.

See `docs/DATA_SAFETY.md` for the complete data and runtime policy.
