"""The central loader (plan section 8.1).

This is the only place in the project that reads the raw CSVs. It exists so that
four archive-specific hazards are handled exactly once:

1. Region code `NA` must stay "North America" rather than becoming null, so the
   reader is configured with `keep_default_na=False` and per-column null tokens.
2. Dates are parsed explicitly with a fixed format; a malformed date is an error,
   never a silently coerced `NaT`.
3. Fact rows referencing an unknown account are rejected rather than dropped.
4. Latent ground-truth columns are loaded but never handed to runtime code; that
   separation is enforced by the repository layer, not by convention.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from meridian.data.paths import raw_tables_directory
from meridian.data.schemas import TABLE_SPECS, TableSpec

_DATE_FORMAT = "%Y-%m-%d"


class DataValidationError(RuntimeError):
    """Raised when the archive violates a documented guarantee.

    Carries every violation found, not just the first, so a broken archive can be
    diagnosed in one pass.
    """

    def __init__(self, table: str, problems: list[str]) -> None:
        self.table = table
        self.problems = problems
        detail = "\n  - ".join(problems)
        super().__init__(f"{table}: {len(problems)} validation problem(s)\n  - {detail}")


@dataclass(frozen=True)
class RawDataset:
    """Validated raw tables, including latent columns.

    Runtime code must not consume this directly. Use
    :class:`meridian.data.repository.RuntimeRepository`, which strips latent
    fields and enforces the point-in-time cutoff.
    """

    accounts: pd.DataFrame
    usage_weekly: pd.DataFrame
    support_tickets: pd.DataFrame
    csm_notes: pd.DataFrame
    external_events: pd.DataFrame
    account_features: pd.DataFrame
    renewal_outcomes: pd.DataFrame

    def table(self, name: str) -> pd.DataFrame:
        """Return one table by name, as a defensive copy."""

        frame = getattr(self, name, None)
        if not isinstance(frame, pd.DataFrame):
            raise KeyError(f"unknown table {name!r}")
        return frame.copy()


def _read_table(spec: TableSpec, directory: Path) -> pd.DataFrame:
    """Read one CSV with archive-safe reader settings, before validation."""

    path = directory / spec.filename
    if not path.is_file():
        raise DataValidationError(spec.name, [f"missing source file {path}"])

    # keep_default_na=False is what preserves region "NA". Columns that are
    # genuinely nullable opt back in explicitly below.
    frame = pd.read_csv(path, keep_default_na=False, dtype=str)

    for column in spec.nullable_columns:
        frame[column] = frame[column].replace("", None)
        declared = str(spec.schema.columns[column].dtype)
        if not declared.lower().startswith(("int", "float")):
            continue
        # Nullable numerics arrive as strings like "5.0". pandera cannot coerce
        # that straight to Int64, so normalise through float first.
        numeric = pd.to_numeric(frame[column], errors="coerce")
        malformed = numeric.isna() & frame[column].notna()
        if bool(malformed.any()):
            examples = frame.loc[malformed, column].head(3).tolist()
            raise DataValidationError(
                spec.name,
                [f"{column}: {int(malformed.sum())} non-numeric value(s), e.g. {examples}"],
            )
        if declared == "Int64":
            frame[column] = numeric.astype("Int64")
        else:
            frame[column] = numeric

    for column in spec.boolean_columns:
        frame[column] = frame[column].map({"True": True, "False": False})
        if frame[column].isna().any():
            bad = int(frame[column].isna().sum())
            raise DataValidationError(spec.name, [f"{column}: {bad} value(s) are not True/False"])

    for column in spec.date_columns:
        parsed = pd.to_datetime(frame[column], format=_DATE_FORMAT, errors="coerce")
        malformed = parsed.isna() & frame[column].notna() & (frame[column] != "")
        if bool(malformed.any()):
            examples = frame.loc[malformed, column].head(3).tolist()
            raise DataValidationError(
                spec.name,
                [f"{column}: {int(malformed.sum())} malformed date(s), e.g. {examples}"],
            )
        frame[column] = parsed

    return frame


def _validate_table(spec: TableSpec, frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the table's schema, reporting every failure at once."""

    try:
        return spec.schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as error:
        cases = error.failure_cases
        problems = [
            f"{row.column}: {row.check} (e.g. {row.failure_case!r})"
            for row in cases.drop_duplicates(subset=["column", "check"]).head(20).itertuples()
        ]
        raise DataValidationError(spec.name, problems) from error


def _validate_account_foreign_keys(name: str, frame: pd.DataFrame, known: set[str]) -> None:
    """Reject fact rows whose `account_id` is not present in `accounts`."""

    orphans = sorted(set(frame["account_id"].unique()) - known)
    if orphans:
        raise DataValidationError(
            name,
            [f"{len(orphans)} unknown account_id value(s), e.g. {orphans[:5]}"],
        )


def load_raw_dataset(directory: Path | None = None) -> RawDataset:
    """Read, coerce, and validate every raw table.

    Args:
        directory: Directory holding the seven CSVs. Defaults to the extracted
            archive under `data/raw/`.

    Returns:
        A frozen :class:`RawDataset` whose frames have passed schema, key, and
        categorical validation.

    Raises:
        DataValidationError: If any table is missing, malformed, violates its
            schema, or references an unknown account.
    """

    source = directory if directory is not None else raw_tables_directory()
    frames: dict[str, pd.DataFrame] = {}
    known_accounts: set[str] = set()

    for spec in TABLE_SPECS:
        frame = _validate_table(spec, _read_table(spec, source))
        if spec.name == "accounts":
            known_accounts = set(frame["account_id"].unique())
        elif spec.has_account_foreign_key:
            _validate_account_foreign_keys(spec.name, frame, known_accounts)
        frames[spec.name] = frame

    return RawDataset(**frames)
