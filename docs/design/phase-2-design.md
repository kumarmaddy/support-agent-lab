# Phase 2 Design: Knowledge-Base Answers and More Ticket Types

- Version: 0.1 (draft for review)
- Date: 2026-10-09
- Owner: Kumar Maddipatla, Project Lead
- Builds on: phase-1-design.md v1.6, ADR-006 (fixed pipeline), ADR-007 (qwen2.5:7b, read prompt v4)

## 1. Goal
Extend the pipeline beyond order status so that it (a) answers general policy questions from the knowledge base and cites the article it used, (b) says "I don't know" and hands over when the knowledge base does not cover a question, and (c) handles returns, refunds, cancellations and address changes. Exit targets are measured on the development split and recorded in a Phase 2 evaluation report.

## 2. Who chooses the article
The 21 knowledge-base articles are short (at most 250 words). Two different situations need two different mechanisms:
- **Transactional tickets** (order status, return, refund, cancellation, address change): the right article follows from the decision, not from the ticket's words. A late shipment cites the late-shipment article because the order is late. Code keeps choosing the article, as in Phase 1.
- **Knowledge questions** (product_info: sizing, care, shipping times, return rules asked in general): the right article depends on what the customer asks. These use retrieval.

Retrieval therefore sits beside the decision rules; it does not replace them. A ticket's text never selects an action.

## 3. Retrieval baseline (stage 2.2)
`src/kb/retrieve.py` ranks articles with BM25, a word-matching score, over title, key facts and details. The internal guidance is never indexed or returned. It needs no model, runs in milliseconds and ranks identically every time. `src/evaluation/retrieval.py` scores it against the development labels: every ticket that lists required articles is a test (145 tickets).

| Category | n | hit@1 | hit@3 |
|---|---|---|---|
| product_info (the real retrieval use) | 8 | 62% | 88% |
| refund | 30 | 63% | 90% |
| account | 12 | 92% | 100% |
| return_exchange | 32 | 38% | 75% |
| cancellation | 14 | 50% | 71% |
| address_change | 10 | 50% | 80% |
| order_status | 35 | 26% | 40% |
| All | 145 | 49% | 72% |

(hit@k: a required article is among the first k results.)

Reading: word matching on whole tickets is weak where the article depends on order state (order status 26%), which confirms section 2. For knowledge questions it works about two times in three at rank 1. That is not enough to answer from the first hit without a check, and n = 8 is too small to trust the figure.

## 4. Decisions needed
1. **A larger retrieval test set.** The development split holds only 8 knowledge questions. Options: (a) write about 30 knowledge-question probes by hand with labelled articles, kept separate from the frozen dataset and labelled as a development probe set; (b) add them to a new dataset version (v1.1), which re-freezes the manifest. Recommended: (a), because it leaves the frozen dataset and its hashes untouched.
2. **Embeddings.** Compare BM25 with a local embedding model through Ollama (for example nomic-embed-text) and a hybrid of both, on the same test, and choose by recall@k and cost (ADR-009). Recommended: yes, stage 2.3.
3. **"I don't know" rule.** The answer is given only when the best article scores above a threshold and clearly beats the second. The threshold is set on development data and re-checked on held-out in Phase 4. Five development tickets have no required article; their best BM25 score ranges from 0 to 4.4, which overlaps scores of answerable questions, so the rule cannot be settled from word matching alone.

## 5. Stages
| Stage | Content |
|---|---|
| 2.2 | This design; BM25 retriever; retrieval evaluation; baseline numbers (done) |
| 2.3 | Knowledge-question probe set; embedding and hybrid comparison; ADR-009 |
| 2.4 | Knowledge-question path in the pipeline: retrieve, decide to answer or hand over, reply from article key facts, citation validator rule |
| 2.5 | Returns, refunds, cancellations, address changes: reading, decision rules, reply facts (read-only; proposed actions go to a person) |
| 2.6 | Escalation summary for the person who receives a ticket |
| 2.7 | Phase 2 evaluation (3B and 7B), citation validity, blind review, report, exit review |

## 6. Safety rules carried over
Ticket and article text are data, not instructions; the reply model sees only verified facts and article key facts; every reply passes the validator; any failure falls back to a template or a hand-over; write actions stay disabled until Phase 3.

## 7. Risks touched
R8 (fabricated policy or facts): citation validity becomes a measured rule in 2.4. R9 (injection): article text is data. R16 (small samples): the probe set and intervals address it. R1 (accuracy of small models): compared in 2.7.