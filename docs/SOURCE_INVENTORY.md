# Source Inventory

Inventory date: 2026-08-31

SHA-256 hashes identify the exact source versions reviewed during onboarding.

## Course and design sources

| Source | Role | SHA-256 |
| --- | --- | --- |
| `Capstone Checkpoint 1.1 Capstone Project Scoping and Initial Agent Design.docx` | Initial problem, users, environment, actions, feedback | `471ab2c3521fe24f08d697a241d23fbdefcbf151af9333374c357b4a2d3508a9` |
| `Capstone_Checkpoint_2.1_Agent_Design_Refinement.docx` | ReAct, memory, deterministic tool, retrieval tool, coverage | `a05325887be91cccf83fd865cc40796a776b264a111449774f8aadd5ab8c95a0` |
| `Capstone_Checkpoint_3.1_RAG_and_Retrieval_Design_Integration.docx` | Retrieval sources, filters, chunking, failure behavior | `64dfde921660de7d19c8ce21dda82f2274f929f870ae986dd1af6fb05c43e671` |
| `Capstone_Checkpoint_4.1_Tree_of_Thought_Integration.docx` | Conflict-gated ToT, bounds, pruning, escalation | `4a722d695a1750175901fa31ab022f71ecee898b42b3036380cc8322e4c4e04e` |
| `Capstone_Checkpoint_5.1_Multi_Agent_Architecture_and_Coordination_Plan.docx` | Four agents, LangGraph coordination, shared state | `a23b1a7f68a288dc012ce3bddf6f348f00a34ecfa14f59989b143a281e966654` |
| `Capstone_Checkpoint_6.1_Safety_Guardrails_and_Human_Intervention_Plan.docx` | Layered safety, evaluation, confidence, human review | `7648b3cd2bf55e809218706c37b0cefa35b0e465e0c99e8e17135769c9c555db` |
| `Meridian_Autonomous_System_Implementation_Plan.md` | Latest build specification and conflict resolution | `d9315f58979a814397a6c2dc46d86b0565086a38ef1ed2944ead890b5166957d` |
| User-provided Module 7 Canvas text | Final deliverables and submission checklist | `fcd5a26cee3109404a85fe8f4ca8695edc4e3edc683727088e93fd8941dee15f` |

All six checkpoint documents rendered successfully and were visually reviewed. They contain no detected Word comments or tracked insert/delete markup.

## Dataset sources

| Source | Role | SHA-256 |
| --- | --- | --- |
| `meridian-account-health.zip` | Immutable canonical archive | `0b6a82d8dbb3b62b29cad0e24c7025ff99ed3d5114e427016ffb6543efa7d26f` |
| Extracted `README.md` | Dataset intent, package map, caveats | `8d92a9ad68b3c515b6fd76015dd81f72d23f31af307d8a1e7d210eccf21f5d44` |
| Extracted `DATA_DICTIONARY.md` | Field-level schema and leakage markings | `19ef4a91f994f4bfdca3c373e63a05c16043656dc95cdd9110d7dec74159cbf1` |
| Extracted `config.py` | Seed, as-of date, forecast horizon, generation constants | `edf0761c8515537458180e96dcca52fc643786ed60bde6fd8431f7d3f6bba692` |
| Extracted `eval/validation_report.md` | Generated row counts, outcome mix, causal sanity checks | `a678d65b1695ab55bf547683bbf1505629573896c8907e45c741f87c8fcff030` |

## Extracted package summary

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

## Deferred source references

The Module 7 text references the following items, but the user has intentionally deferred them:

- Final capstone report template
- Final presentation planning outline
- Any separate detailed scoring rubric beyond the provided assignment directions and checklist

Do not track these as missing sources or active blockers unless the user reactivates them.
