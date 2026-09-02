# Source inventory

SHA-256 hashes identify the exact versions of the inputs this system was built
against. They exist so a reader can confirm that the data in the repository is
the data the reported numbers came from.

## Design specification

| Source | Role | SHA-256 |
| --- | --- | --- |
| `docs/Meridian_Autonomous_System_Implementation_Plan.md` | Build specification; resolves earlier design conflicts | `d9315f58979a814397a6c2dc46d86b0565086a38ef1ed2944ead890b5166957d` |

The design history behind that specification — what an earlier decision
committed to, and what the build did with it — is in `docs/DESIGN_EVOLUTION.md`.

## Dataset sources

| Source | Role | SHA-256 |
| --- | --- | --- |
| `meridian-account-health.zip` | Immutable canonical archive | `7d8d064b8293986d4aaddd76d161248e7baccbef60bf8dc193292b325cd9001a` |
| Extracted `README.md` | Dataset intent, package map, caveats | `c1169ff767f60661157abe68fd43125197c9b84d3bce0a4478e37d18d9e2a47b` |
| Extracted `DATA_DICTIONARY.md` | Field-level schema and leakage markings | `19ef4a91f994f4bfdca3c373e63a05c16043656dc95cdd9110d7dec74159cbf1` |
| Extracted `config.py` | Seed, as-of date, forecast horizon, generation constants | `edf0761c8515537458180e96dcca52fc643786ed60bde6fd8431f7d3f6bba692` |
| Extracted `eval/validation_report.md` | Generated row counts, outcome mix, causal sanity checks | `a678d65b1695ab55bf547683bbf1505629573896c8907e45c741f87c8fcff030` |

`dataset/` holds a browsable, byte-identical copy of the generator source inside
that archive; `test_dataset_source.py` fails the build if the two ever diverge.

## Package contents

| Artifact | Verified count |
| --- | ---: |
| Accounts | 260 |
| Weekly usage rows | 67,223 |
| Support tickets | 6,408 |
| CSM notes/QBRs | 6,420 |
| External events | 595 |
| Account RAG records | 12,828 |
| Combined account + KB records | 12,860 |
| Knowledge-base documents | 32 |
| Golden questions | 23 |
| Guardrail cases | 36 |

Every table in the archive reproduces byte for byte from the generator at seed
`20260721`, which `test_data_reproducibility.py` checks on every run.
