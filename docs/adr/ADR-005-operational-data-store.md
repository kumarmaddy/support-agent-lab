# ADR-005: Operational data store

- Status: Accepted
- Date: 2026-10-08
- Owner: Kumar Maddipatla, Project Lead
- Related: charter section 7 (constraints), risk R2 (memory on 16 GB hardware), spec NFR-2 (audit trail) and NFR-4 (idempotent actions); data design sections 4 and 9; ADR-004

## Context
The agent reads orders, shipments, payments, refunds, returns and tickets, and in later phases writes proposed actions,
approvals and an audit trail. The store must run at zero cost on one Windows laptop with 16 GB RAM, share memory with a local
model (risk R2), and support the evaluation method: byte-for-byte reproducible datasets, row-level hashing, and read-only
access for every tool that must not change data.

## Options considered
| Option | Assessment |
|--------|------------|
| A. SQLite file (Python standard library) | No server, no install, no containers; transactional; foreign keys; one file per dataset split |
| B. PostgreSQL (local service or container) | Closer to a production system and better for concurrent writers, but adds a service and memory use that compete with the model, and charter constraints exclude containers in v1 |
| C. Flat files (JSON or CSV) | Simplest, but no integrity constraints, joins or transactions; idempotency and the audit trail would have to be built by hand |
| D. DuckDB | Strong for analytics, not designed for the transactional, row-level write pattern of the approval workflow |

## Decision
Option A. One SQLite database file per dataset split, accessed through the Python standard library.
- Foreign keys are enforced on every connection. Money is stored as integer cents.
- Ground-truth labels are stored outside the database (`data/labels/`), so no tool that can open the database can read them.
- Every component that must not change data opens the file read-only (SQLite URI `mode=ro`). The manual baseline tool already does so.
- Write-capable tools, added in Phase 3, go through the policy engine (ADR-004) and write to the audit log with idempotency keys.
- The vector store for knowledge-base retrieval and the trace store are separate decisions, taken in Phases 2 and 1 respectively.

## Evidence
| Measure | Result |
|---------|--------|
| Development database | 12 tables, 731 orders, 1,109 order items, 756 payments, 150 tickets; 0.5 MB |
| Labels file | 150 labels; 0.14 MB |
| Aggregate query (orders joined to items) | about 2 ms |
| Reproducibility | Every table's rows hashed (SHA-256, rowid order) for both splits and recorded in `data/manifest.json`; the hashes matched on Windows and Linux when compared at stage 0.4d-3 |
| Environment recorded in the manifest | SQLite 3.45.1, CPython 3.13 |
| Read-only access | Verified by the baseline tool, which opens the database with `mode=ro` |

## Consequences
- Single-writer storage is sufficient for v1: one agent process and one approval service. This is not a claim about production scale.
- The default rollback-journal mode is in use. When the agent and the approval service write concurrently (Phase 3), the journal mode is reviewed and recorded in the build log; write-ahead logging is the expected choice.
- The schema uses standard SQL types, so a later move to a server database changes the connection layer, not the data model.
- Row-level hashing of the frozen dataset depends on the SQLite version recorded in the manifest. Upgrading it requires running `freeze verify` and recording the result.

## Assumptions and limitations
- The data is synthetic and small; the timings describe this dataset, not a production workload.
- Concurrency behaviour is untested because v1 has no concurrent writers.

## Note on numbering
ADR-004 records the refund approval thresholds. The vector-store decision takes the next free number.