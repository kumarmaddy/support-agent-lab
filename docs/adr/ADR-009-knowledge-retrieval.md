# ADR-009: Knowledge-base retrieval method

- Status: Accepted (2026-10-09, project lead)
- Date: 2026-10-09
- Owner: Kumar Maddipatla, Project Lead

## Context
Phase 2 adds answers to general policy questions from the 21-article knowledge base, with citations and an "I don't know" path. The project is local and zero cost, and runs on a CPU-only 16 GB laptop (ADR-003). The right article for transactional tickets follows from the decision rules, so retrieval is only needed for knowledge questions (phase-2-design.md, section 2).

## Options
1. BM25 word matching: no model, deterministic, standard library only.
2. Local embeddings (nomic-embed-text through Ollama) with cosine similarity.
3. A hybrid of both by reciprocal rank fusion.
4. A vector database (Chroma or FAISS): not considered necessary for 21 articles.

## Evidence (development split; evidence files `retrieval-probes-bm25.txt` and `retrieval-embedding-hybrid-runs.txt`)
| | BM25 | Embeddings | Hybrid |
|---|---|---|---|
| Probe questions, hit@1 | 27/36 (75%) | 30/36 (83%) | 31/36 (86%) |
| Probe questions, hit@3 | 32/36 (89%) | 35/36 (97%) | 34/36 (94%) |
| Tickets of type product_info, hit@1 (n = 8) | 62% | 100% | 88% |
| Highest score on an unanswerable probe | not separable | 0.715 | not usable (fused scores 0.016-0.033) |

Embeddings against BM25 on the probes: 5 questions right only for embeddings, 2 only for BM25 (sign test p = 0.45): the direction is consistent but not statistically reliable.

## Decision
Use embeddings (nomic-embed-text) with cosine similarity for knowledge questions, held in memory (the 21 article vectors are computed at start-up). Keep BM25 as the documented baseline and as the fallback if the embedding model is unavailable (the question is then handed to a person, not answered). Do not adopt the hybrid: it does not beat embeddings alone and its scores cannot carry a threshold. No vector database.

## Consequences
- One more local model to pull and pin (digest recorded in each run).
- Retrieval alone cannot decide "I don't know": the answer needs the three gates in the design (score at least 0.65, a model check that the article answers the question, and a validated reply that cites the article).
- The 0.65 threshold and the choice are set on 48 probes and 145 development tickets and are re-checked on the held-out split in Phase 4.
- The probe set was written by the system's author and reviewed by the project lead; there is no independent reviewer.
- Reverse the decision if the embedding model proves unstable between runs, or if the held-out hit@1 for knowledge questions falls below BM25.