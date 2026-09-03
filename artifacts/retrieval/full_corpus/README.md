# The chunking ablation over the whole portfolio

`docs/PHASE_3_STATUS.md` recorded a limitation: the published ablation compares
the two chunking strategies over 853 documents from the 18 benchmark accounts
rather than all 260, so "the small gap between the arms rests on a small
corpus".

This directory is the same ablation over the full portfolio -- 10,459 documents
and 17,140 chunks, twelve times the corpus -- produced by:

```bash
./scripts/python_in_docker.sh python scripts/evaluate_retrieval.py \
  --full-corpus --output artifacts/retrieval/full_corpus
```

## Result

Every metric is identical to four decimal places.

| Metric | 853 docs / 18 accounts | 10,459 docs / 260 accounts |
| --- | --- | --- |
| parent-child chunks | 1,464 | 17,140 |
| fixed-length chunks | 1,029 | 12,037 |
| Recall@5, parent-child minus fixed-length | +0.0144 | +0.0144 |
| Precision@5 | -0.0108 | -0.0108 |
| MRR | -0.0627 | -0.0627 |
| nDCG | -0.0424 | -0.0424 |

## Why it does not move, which is the actual finding

Not a coincidence and not a mistake. `run_benchmark` issues every query against
a named account (`service.search(account_id, query.query)`), and the account
lane filters by `account_id` in the metadata store before ranking. The 242
accounts added here contribute candidates that are excluded before they can
compete, and the knowledge-base lane sees the same 32 articles either way.

So the corpus grew twelvefold and the set of documents that could be returned
for any graded query did not change at all. That is worth more than the
ablation it was run to check: it is a direct measurement that cross-account
documents cannot pollute a result, which is the property the wrong-account
citation counter asserts from the other direction.

It also means the original shortcut was sound rather than merely cheap, and
that the honest reading of the gap is unchanged: parent-child retrieves more of
the right documents (Recall@5 +0.0144) and ranks them worse (MRR -0.0627, nDCG
-0.0424). The published run remains the one in the parent directory.
