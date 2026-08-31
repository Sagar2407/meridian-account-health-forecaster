#!/usr/bin/env python3
"""Query the local, point-in-time-safe retrieval index and print typed JSON."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from meridian.data.repository import RuntimeRepository, UnknownAccountError  # noqa: E402
from meridian.retrieval.contracts import (  # noqa: E402
    ACCOUNT_SOURCE_FAMILIES,
    AccountSourceFamily,
)
from meridian.retrieval.index import IndexManifestError, load_verified_index  # noqa: E402
from meridian.retrieval.search import RetrievalService  # noqa: E402


def _iso_date(value: str) -> date:
    """Parse one strict ISO date for argparse."""

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO date such as 2026-06-28") from error


def _parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("account_id", help="Synthetic Meridian account id, for example ACC-1089")
    parser.add_argument("query", help="Qualitative evidence question")
    parser.add_argument(
        "--as-of",
        type=_iso_date,
        dest="requested_as_of",
        help="Optional earlier cutoff; later dates are clamped to the account cutoff",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=ACCOUNT_SOURCE_FAMILIES,
        dest="allowed_sources",
        help="Authorize an account source family; repeat as needed (default: all)",
    )
    parser.add_argument(
        "--require-source",
        action="append",
        choices=ACCOUNT_SOURCE_FAMILIES,
        dest="required_sources",
        help="Require a source family for coverage grading; repeat as needed",
    )
    parser.add_argument(
        "--guidance-only",
        action="store_true",
        help="Do not require account evidence; useful for knowledge-base questions",
    )
    parser.add_argument(
        "--without-knowledge-base",
        action="store_true",
        help="Disable the separate general-guidance lane",
    )
    corroboration = parser.add_mutually_exclusive_group()
    corroboration.add_argument(
        "--require-corroboration",
        action="store_true",
        dest="require_corroboration",
        help="Require two independent relevant parent documents",
    )
    corroboration.add_argument(
        "--no-corroboration",
        action="store_false",
        dest="require_corroboration",
        help="Disable inferred corroboration for this request",
    )
    parser.set_defaults(require_corroboration=None)
    parser.add_argument(
        "--maximum-age-days",
        type=int,
        help="Treat account evidence older than this at the cutoff as stale",
    )
    parser.add_argument(
        "--index-directory",
        type=Path,
        help="Override data/indexes (intended for tests and local experiments)",
    )
    parser.add_argument(
        "--allow-stale-index",
        action="store_true",
        help="Development-only escape hatch; serve despite a corpus digest mismatch",
    )
    return parser


def _as_sources(values: list[str] | None) -> tuple[AccountSourceFamily, ...] | None:
    """Narrow argparse strings to the validated source-family type."""

    if values is None:
        return None
    known = set(ACCOUNT_SOURCE_FAMILIES)
    if any(value not in known for value in values):
        raise ValueError("unknown source family")
    return tuple(dict.fromkeys(values))  # type: ignore[return-value]


def _result_payload(result: Any, index_version: str) -> dict[str, Any]:
    """Return JSON-ready output including computed convenience fields."""

    payload: dict[str, Any] = result.model_dump(mode="json")
    payload["insufficient_evidence"] = result.insufficient_evidence
    payload["missing_families"] = list(result.missing_families)
    payload["index_version"] = index_version
    return payload


def main(argv: list[str] | None = None) -> int:
    """Validate the live corpus/index pair, retrieve, and print JSON."""

    args = _parser().parse_args(argv)
    try:
        if args.maximum_age_days is not None and args.maximum_age_days < 1:
            raise ValueError("--maximum-age-days must be positive")
        repository = RuntimeRepository()
        index = load_verified_index(
            repository,
            args.index_directory,
            allow_mismatch=args.allow_stale_index,
        )
        service = RetrievalService(index, repository)
        result = service.retrieve(
            args.account_id,
            args.query,
            requested_as_of=args.requested_as_of,
            allowed_source_families=_as_sources(args.allowed_sources),
            include_knowledge_base=not args.without_knowledge_base,
            required_source_families=_as_sources(args.required_sources) or (),
            require_account_evidence=not args.guidance_only,
            require_corroboration=args.require_corroboration,
            maximum_age_days=args.maximum_age_days,
        )
    except (FileNotFoundError, IndexManifestError, UnknownAccountError, ValueError) as error:
        print(f"retrieval failed: {error}", file=sys.stderr)
        return 2

    payload = _result_payload(result, index.manifest.index_version)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
