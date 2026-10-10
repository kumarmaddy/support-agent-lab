# Phase 2 Design: Knowledge-Base Answers and More Ticket Types

- Version: 0.5 (draft for review)
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

### 3.1 Probe questions and embeddings (stage 2.3)
Because the development tickets hold only 8 knowledge questions, a separate probe file (`data/probes/knowledge_questions.jsonl`: 36 answerable questions covering all 21 articles and 12 the knowledge base cannot answer) was written before any retrieval result was seen. Three methods were compared: BM25, embeddings (nomic-embed-text through Ollama, cosine similarity) and a rank-fusion hybrid of the two.

| Method | Probes hit@1 (95% interval) | Probes hit@3 | Tickets: product_info hit@1 / hit@3 (n = 8) | All 145 tickets hit@1 / hit@3 |
|---|---|---|---|---|
| BM25 | 75% (59-86%) | 89% | 62% / 88% | 49% / 72% |
| Embeddings | 83% (68-92%) | 97% | 100% / 100% | 63% / 86% |
| Hybrid | 86% (71-94%) | 94% | 88% / 88% | 66% / 86% |

Paired on the probes, embeddings against BM25: right only for embeddings on 5 questions, only for BM25 on 2 (sign test p = 0.45). The differences are consistent in direction but not statistically reliable at this sample size. The hybrid does not beat embeddings alone, and its fused scores (0.016 to 0.033) cannot carry a threshold, so it is dropped.

### 3.2 "I don't know"
With embeddings the best score separates unanswerable from answerable questions much better than with BM25: of the 12 unanswerable probes, the highest score is 0.715 and the five unanswerable development tickets score 0.54 to 0.61. A minimum score of 0.65 keeps 81% of answerable probes correctly answered, lets 14% be answered with a wrong article and lets 1 of 12 (8%) unanswerable questions through. A stricter 0.75 leaves no wrong answers but answers only 61% correctly. A score alone therefore cannot make the call, so the rule has three gates (section 4).

## 4. Decisions
1. Probe set: written (36 + 12), reviewed by the project lead, kept apart from the frozen dataset. Decided.
2. Method: embeddings with nomic-embed-text for knowledge questions; BM25 is kept as a measured baseline (ADR-009). Decided.
3. Answer or hand over, three gates, all of which must pass:
   - Gate 1: the best article's cosine score is at least 0.65 (initial value, set on the probes and development tickets; re-checked on held-out in Phase 4).
   - Gate 2 (stage 2.4): a short model check, with a fixed yes/no schema, that the article's key facts answer the question; measured on the probes.
   - Gate 3: the reply is validated against the article's key facts and must cite the article; any failure uses the template hand-over.
   Any failed gate means a hand-over to a person with no answer sent.

### 4.1 As built (stage 2.4)
- The path is opt-in (`python -m src.agent.run --knowledge`) so that the Phase 1 results stay reproducible; it applies only to tickets the reader calls product_info and that carry no legal threat. Other categories and every legal threat behave as before.
- The reply writer sees only the article's key facts (without the internal cross-references), never the ticket or the question. The reply therefore restates the article and does not tailor itself to the question; the model check in gate 2 decides whether that article is the right one to send.
- The citation is the article id on the resolution; the customer-facing text carries no article id.
- A separate validator (`validate_knowledge_reply`) applies to knowledge replies because policy text legitimately contains words that the order-status rules forbid (refund, within 30 days, contact us). Those words are allowed only when a key fact uses them; numbers must appear in the key facts; no dates, amounts, order numbers, article ids, internal-guidance wording or prompt wording; each sentence must share two content words with the key facts. The last rule catches invented content, not a reversed claim, so a person reviews the answers.
- Four probe labels were widened after the retrieval comparison, because two articles state the same fact (P-005 and P-008 also accept KB-ORD-01, P-029 also KB-SHP-03, P-030 also KB-ORD-01, P-024 also KB-RET-01). They apply to every method alike; the retrieval figures in section 3 use the original labels.

## 5. Stages
| Stage | Content |
|---|---|
| 2.2 | This design; BM25 retriever; retrieval evaluation; baseline numbers (done) |
| 2.3 | Knowledge-question probe set; embedding and hybrid comparison; ADR-009 (done) |
| 2.4 | Knowledge-question path in the pipeline: retrieve, three gates, reply from article key facts, knowledge validator (built; measured on the probes by the project lead's run) |
| 2.5 | Returns, refunds, cancellations, address changes: reading, decision rules, reply facts (read-only; proposed actions go to a person) |
| 2.6 | Escalation summary for the person who receives a ticket |
| 2.7 | Phase 2 evaluation (3B and 7B), citation validity, blind review, report, exit review |

## 5a. Cancellations and address changes (stage 2.5a)
Opt-in with `--transactions`; without it these tickets go to a person as in Phase 1. The agent proposes and a person acts: no tool writes.
- **Identify.** Same read-only lookup as order status (customer by email, order by number or the single open order). The same request-for-information and escalation outcomes apply when the account or order cannot be established.
- **Cancellation (KB-CAN-01).** Order processing: `propose_cancellation`. Order shipped: `decline_policy`, stating the carrier and tracking number. Any other state goes to a person.
- **Address change (KB-ADR-01).** Order processing with a usable address: `propose_address_change`. Without one: `request_info` (`address_missing`). Order shipped: `decline_policy`. Any other state goes to a person.
- **The address is the customer's own text.** A second small model call copies it from the ticket (prompt `extract_address.v1`). Code accepts it only if it appears word for word in the ticket after white space is normalised, is at most 100 characters, has at least two words and a digit, and uses only letters, digits and `, . \' # / -`. Anything else is treated as no address. The call is made only when the order is processing, so it is never made when its result would not be used.
- **Replies are written by code** (templates). A proposal tells the customer that a colleague will confirm the change; no reply says that anything has been cancelled or changed. This removes model-wording risk from the first transactional actions; model-written wording can be compared later.
- **Scoring.** A run made with `--transactions` records it in `run.json`; the scorer then counts scenarios S13-S16 and the S24 cancellation as in scope and compares the proposed address with the labelled one exactly. `decline_policy` counts as an answer; a proposal for an out-of-scope ticket counts as wrongly answered.
- **Not covered here.** Returns, exchanges, replacements and refunds (2.5b, 2.5c); the final state of a delivered, cancelled or returned order is left to a person.

## 5b. Returns, exchanges and replacements (stage 2.5b)
Part of `--transactions`. The agent proposes and a person acts; no tool writes.
- **What is asked.** A second small model call (`read_request.v1`) reports the kind of request (return, exchange, replacement, refund or unclear), the product as the customer wrote it, and the requested size. Code keeps only what the ticket supports: the product phrase must appear in the ticket, the size must be one of XS-XXL or 7-13 and stand alone in the ticket text. The call is made only for a delivered order.
- **Which item.** The phrase is matched to the order's own product names (a spelling slip still matches; two close candidates, or none, do not). Order lines now carry the final-sale flag from the products table (read-only).
- **The window.** Counted in code, from the delivery date to the day the request was received. KB-RET-01 says a return "requested on the thirtieth day" is accepted, so day 30 is inside and day 31 is not. The facts record the request date and the count.
- **Rules, in this order.** Delivered orders only (others go to a person). Refund and unclear requests go to a person (refunds are stage 2.5c). Replacement: inside the window, `propose_replacement` (KB-REF-03); outside, a person. Return or exchange outside the window: `decline_policy` (KB-RET-01). No item pinned down: a return is still proposed when nothing in the order is final sale; otherwise, and for any exchange, the customer is asked which item. Final-sale item: `decline_policy` (KB-RET-03). Return: `propose_return_label` (KB-RET-01). Exchange: needs a size different from the current one, otherwise the customer is asked for it (KB-RET-04); an item without sizes goes to a person; else `propose_exchange`.
- **Replies are written by code**; no reply promises a refund or says the return, exchange or replacement has been arranged.
- **Known label difference.** The dataset counts delivery days to its snapshot date (2026-10-06); tickets were received on earlier days. The agent follows the policy text. The two give different answers for one development ticket (T-000091: delivered 5 September, received 5 October, day 30 by the policy, day 31 by the snapshot). It is reported as a miss, not hidden. The scorer does not compare `days_since_delivery` with the label; it checks that the agent's count matches its own request date and compares the window flag and the delivery date.
- **Scope in scoring.** Scenarios S05-S08, S11 (its return_exchange tickets) and the S24 return_exchange ticket join the in-scope set. S11's refund tickets wait for stage 2.5c.

## 6. Safety rules carried over
Ticket and article text are data, not instructions; the reply model sees only verified facts and article key facts; every reply passes the validator; any failure falls back to a template or a hand-over; write actions stay disabled until Phase 3.

## 7. Risks touched
R8 (fabricated policy or facts): citation validity becomes a measured rule in 2.4. R9 (injection): article text is data. R16 (small samples): the probe set and intervals address it. R1 (accuracy of small models): compared in 2.7.