# Phase 0 environment report

Verified on 2026-08-31 from the user's Docker-enabled terminal:

| Component | Observed status |
| --- | --- |
| Docker | Engine 29.7.2, Compose v5.4.0; the full gate runs in containers |
| Python runtime used for the gate | 3.12.14, from the `uv` container image |
| Node.js runtime used for the gate | 22, from `node:22-alpine` |
| pnpm used for the gate | Pinned by `packageManager` to 11.24.0, provisioned by Corepack |
| External package registry access | Available; both lockfiles resolved successfully |

The supported project targets are Python 3.11–3.13, uv 0.12, Node.js 22.12–24, pnpm 11, and Docker
Compose v2.

There is no host toolchain on this machine: `node`, `pnpm`, and `uv` are not on `PATH`. Every check
therefore runs inside Docker, and container caches are written to the gitignored `.phase0-cache/`
rather than to `/tmp`, which is not writable by the mapped host UID inside distroless images.

Consequences for day-to-day work:

- `make docker-up` and `make phase0-verify` are the supported entry points.
- `make setup`, `make dev`, `make dev-backend`, and `make dev-frontend` call `uv` and `pnpm`
  directly and will fail until a host toolchain is installed.
- The frontend image `COPY`s source rather than bind-mounting it, so `docker compose build frontend`
  is required before edits appear in the running container.
