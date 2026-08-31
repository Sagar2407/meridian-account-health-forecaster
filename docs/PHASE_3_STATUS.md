# Phase 3 status: RAG ingestion and retrieval evaluation

Status: **Complete; exit gate passed on 2026-08-31**

No language model is involved in this phase. Plan section 11.5 describes a grade, rewrite, and retry
loop; every one of its trigger conditions is decidable from the retrieval result itself, so it is
implemented deterministically behind provider-neutral `RetrievalGrader` and `QueryRewriter`
protocols. A model-backed grader can replace either later without touching the retrieval contracts.
The whole stack therefore runs, and is measurable, with no API key.

Build the index with `make index`, query it with
`make retrieve ACCOUNT=ACC-1089 QUERY="renewal risk"`, and reproduce every number below with
`make evaluate-retrieval`.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Parent-child chunking | PASS | `meridian.retrieval.chunking`; sections merged below 80 and split above 1,200 characters |
| External events as evidence documents | PASS | `_render_event`; the packaged corpus ships none, so they are synthesised |
| BGE embeddings and FAISS index | PASS | `BAAI/bge-small-en-v1.5` through ONNX, flat inner-product index over L2-normalised vectors |
| Metadata filtering, MMR, parent return, citation models | PASS | `meridian.retrieval.search`, `meridian.retrieval.contracts` |
| Grading, rewrite, one retry | PASS | `meridian.retrieval.grading`, `meridian.retrieval.rewrite`; `RetrievalResult.retry_count` capped at 1 |
| Curated retrieval benchmark | PASS | Four families, 243 queries, `meridian_eval.retrieval_benchmark` |
| Chunking ablation | PASS | `meridian_eval.chunking_ablation` |
| Versioned index and corpus manifest | PASS | `index_manifest.json`, `corpus_manifest.json`, digests over text and every governing field |
| Retrieval CLI | PASS | `scripts/retrieve.py`, `make retrieve` |
| Retrieval evaluation report | PASS | This document; per-query CSVs are regenerated into the ignored `artifacts/retrieval/` by `make evaluate-retrieval` |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| Zero wrong-account citations | PASS | 0 across 243 benchmark queries; enforced by SQL filter and re-checked after ranking |
| Zero post-cutoff citations | PASS | 0 across 243 queries, including 23 queries written from documents that postdate the cutoff |
| Target Recall@5 or documented gap | PASS | 0.942 over 139 graded queries |

130 tests passing at 93.8% coverage, ruff and mypy strict clean across 56 files.

## What is indexed

| source | parents | chunks |
| --- | ---: | ---: |
| CSM notes | 5,044 | 11,614 |
| Support tickets | 4,902 | 4,902 |
| External events | 481 | 481 |
| Knowledge base | 32 | 143 |
| **total** | **10,459** | **17,140** |

Only text is indexed. Numeric telemetry never enters the corpus, every account document is filtered
to `min(forecast_as_of_date, 2026-06-28)` before chunking, and `assert_no_latent_text` refuses to
index any document that mentions a forbidden schema field. The knowledge base is not exempt: its
guidance is kept but the forbidden vocabulary is stripped before indexing.

## Benchmark

Four query families, all derived from the corpus rather than hand-written, so the benchmark stays
consistent when the archive is rebuilt.

| family | queries | graded | Recall@5 | Precision@5 | MRR | nDCG |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| knowledge base | 32 | 32 | 0.969 | 0.484 | 0.953 | 0.957 |
| account | 180 | 99 | 0.960 | 0.297 | 0.689 | 0.621 |
| conflicting signal | 8 | 8 | 0.625 | 0.300 | 0.369 | 0.295 |
| point in time | 23 | 0 | — | — | — | — |
| **all** | **243** | **139** | **0.942** | **0.340** | **0.732** | **0.679** |

Point-in-time queries carry no gold set by design. Each is lifted verbatim from a note or ticket
dated after that account's cutoff, which is the strongest probe available: were the document
reachable, a query equal to its own text would rank it first. None was ever returned.

### Safety counters, across all 243 queries

| counter | value |
| --- | ---: |
| wrong-account citations | 0 |
| post-cutoff citations | 0 |
| duplicate-parent citations | 0 |
| hidden documents surfaced by a point-in-time probe | 0 |
| queries returning nothing | 0 |

### Per account probe

| probe | graded accounts | Recall@5 | Precision@5 |
| --- | ---: | ---: | ---: |
| billing | 13 | 1.000 | 0.292 |
| escalation | 12 | 1.000 | 0.317 |
| integration | 12 | 1.000 | 0.350 |
| onboarding | 17 | 1.000 | 0.388 |
| outage | 14 | 1.000 | 0.386 |
| external | 17 | 0.941 | 0.200 |
| renewal_prep | 14 | 0.786 | 0.157 |
| adoption, risk, sponsor | 0 | ungraded | ungraded |

`renewal_prep` is the weakest probe, and understandably so: "Renewal Prep" and "Escalation / Save
Play" are the two rarest note types in the corpus, so several accounts have exactly one gold
document competing against dozens of routine touchpoints.

### How the account gold sets are built

Account probes are graded against labels derived from structured metadata — note type, ticket
category, ticket priority, document family — rather than hand annotation. That keeps the gold set
reproducible and moving with the archive, and it is weak in one specific way worth stating plainly:
a document renders its own type and category into its opening line, so a category-derived label
rewards a retriever that can connect a paraphrased question to that header as well as to the body.

Three probes — `risk`, `adoption`, and `sponsor` — have no defensible structural label and stay
deliberately ungraded rather than being scored against a keyword rule that would mostly measure
itself. They still run, and still count toward the safety and empty-result totals.

## Chunking ablation

Corpus, encoder, metadata filters, top-k, and queries are identical across arms; only the split
differs. Both arms are built over the 18 golden accounts plus the knowledge base. The parent-child
arm reproduces the served index's numbers exactly, which is what makes the comparison
apples-to-apples.

| strategy | chunks | Recall@5 | Precision@5 | MRR | nDCG | conflict coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| parent-child | 1,464 | 0.942 | 0.340 | 0.732 | 0.679 | 0.250 |
| fixed length | 1,029 | 0.928 | 0.351 | 0.794 | 0.722 | 0.250 |

Conflict coverage is identical in both arms, which is consistent with the cause being
polarity-blind ranking rather than chunk shape.

## Two findings worth carrying into later phases

### Retrieval alone does not surface both sides of a conflict

Eight of the eighteen golden accounts show a cross-source contradiction: consistently warm CSM
notes beside adverse market news, or a favourable external event beside a consistently poor quarter.
In six of those eight, the top five citations show only one side. Conflict coverage is 0.25.

The cause is structural rather than a tuning problem. MMR diversifies on embedding redundancy, so it
spreads results across distinct passages, but nothing in the ranking is aware of polarity — and the
majority side usually has far more documents to draw from. The plan already puts a conflict gate in
Phase 6; this measurement says that gate must not assume retrieval has handed it both sides. It
needs to ask for them, most directly by issuing an explicit second retrieval for the minority
polarity.

### The chunking ablation does not vindicate the mandated strategy

The plan mandates parent-child chunking. Holding the corpus, encoder, filters, top-k, and queries
constant, the two arms are close, and fixed-length chunking ranks better on the ordering metrics
while parent-child recalls slightly better. Parent-child is retained, on two grounds that the
ranking metrics do not capture:

- What reaches a reader is the citation's `parent_context`, a bounded window of a coherent section.
  Fixed-length chunks cut mid-sentence, so an excerpt is more often unquotable even when its ranking
  is better.
- Recall@5 is the criterion that matters for evidence gathering. Everything downstream sees all five
  citations, so whether the right document is in the set matters more than its position in it.

This is a judgement call on a small difference, not a result. Stating it as a result would overclaim.

## Known limitations

- **The ablation corpus is 853 documents from the 18 golden accounts, not all 260.** Embedding the
  full corpus twice would add roughly twenty minutes without changing what the comparison controls
  for. The consequence is that the small gap between the arms rests on a small corpus.
- **Downstream answer correctness is not measured.** Plan section 11.6 asks for it; it needs a
  language model to produce an answer to grade, so it is deferred to the phases that have one.
- **Ungraded queries still count.** 104 of 243 carry no gold set: 54 from the three subjective
  account probes, 27 where a structural probe matched no document for that account (an account with
  no billing tickets, say), and the 23 point-in-time probes, whose whole purpose is that nothing
  comes back. Headline Recall@5 is the mean over the 139 graded queries only; the safety counters
  cover all 243.
- **The index is not committed.** It is 40 MB of derived data, rebuilt by `make index` from the
  archive in a few minutes. `load_verified_index` recomputes the corpus digest and refuses to serve
  an index built from different code or data, so a stale index fails loudly instead of quietly
  reporting numbers about a corpus that no longer exists.
