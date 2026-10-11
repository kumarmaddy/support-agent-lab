# ADR-010: Try the knowledge path first for transactional tickets that name no order

- Status: Accepted (2026-10-11)
- Decision owner: Kumar Maddipatla, Project Lead
- Context: A policy question that the reader files under a transaction category never reached the knowledge path (deferred in stage 2.5c). `--knowledge-first` tries the knowledge path first when the reader files a ticket under cancellation, address change, return, exchange or refund, names no order and flags no legal threat; a failed try continues unchanged.
- Evidence: Runs 21c7b5 and 946853 (7B): Set A 116 to 118 of 125; the two tickets that changed (T-000042, T-000145) were answered with the labelled article; no transactional ticket was answered from the knowledge base; Set B unchanged (0 of 25 wrongly answered); three more model calls. The 3B run with the option also answered both, and no transactional ticket from the knowledge base.
- Decision: use `--knowledge --knowledge-first --transactions` as the standard configuration.
- Consequences: only tickets the reader has misfiled are affected (every development transactional ticket names an order). The evidence is two tickets and cannot show a rate; the option is confirmed once on the held-out split in Phase 4. Order-status tickets are never tried first because they need the order.