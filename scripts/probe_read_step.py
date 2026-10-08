"""Run the read-the-ticket step (pipeline steps 1-2) on development tickets with the real local model.

Usage (from the repository root, Ollama running):
    python -m scripts.probe_read_step --limit 40
    python -m scripts.probe_read_step --model qwen2.5:7b

This is a measurement aid, not part of the agent: it compares the model's category with the development labels, so it
lives outside ``src/agent`` (the agent never reads labels). It refuses the held-out split.
"""
import argparse
import collections
import json
import sqlite3
import statistics
from pathlib import Path

from src.agent.model import OllamaClient
from src.agent.prompting import load_prompt
from src.agent.reading import read_ticket


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=Path("data/generated/dev/support.db"))
    p.add_argument("--labels", type=Path, default=Path("data/labels/dev/labels.jsonl"))
    p.add_argument("--model", default="llama3.2:3b")
    p.add_argument("--prompt-version", default="v1")
    p.add_argument("--limit", type=int, default=0, help="first N tickets only (0 = all)")
    p.add_argument("--show-misses", type=int, default=15)
    args = p.parse_args(argv)

    if "heldout" in str(args.db).lower() or "heldout" in str(args.labels).lower():
        raise SystemExit("Refusing to run on the held-out split.")
    labels = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        labels = labels[: args.limit]
    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    model = OllamaClient(model=args.model)
    prompt = load_prompt("read_ticket", args.prompt_version)

    hits, failed, misses, latencies, tokens = 0, 0, [], [], []
    confusion = collections.Counter()
    flag_checks = collections.Counter()
    for lab in labels:
        subject, body = conn.execute("SELECT subject, body FROM tickets WHERE ticket_id=?", (lab["ticket_id"],)).fetchone()
        out = read_ticket(model, prompt, subject, body)
        latencies += [a.latency_ms for a in out.attempts]
        tokens += [a.tokens_in + a.tokens_out for a in out.attempts]
        if not out.ok:
            failed += 1
            continue
        got = out.reading.category
        confusion[(lab["category"], got)] += 1
        if got == lab["category"]:
            hits += 1
        else:
            misses.append((lab["ticket_id"], lab["scenario_id"], lab["category"], got))
        want_legal = bool(lab["priority_attributes"]["chargeback_or_legal_threat"])
        flag_checks["legal_agree"] += out.reading.mentions_chargeback_or_legal == want_legal
        want_deadline = bool(lab["priority_attributes"]["deadline_within_3_days"])
        flag_checks["deadline_agree"] += out.reading.states_hard_deadline == want_deadline
    n, scored = len(labels), len(labels) - failed
    print(f"model {args.model}  digest {model.digest()[:12] or 'unknown'}  prompt {prompt.label} sha256 {prompt.sha256[:12]}")
    print(f"tickets {n}  failed reading {failed}  category agreement {hits}/{scored}"
          + (f" = {hits / scored:.1%}" if scored else ""))
    if scored:
        print(f"chargeback/legal flag agrees with label: {flag_checks['legal_agree']}/{scored}")
        print(f"deadline flag agrees with deadline_within_3_days label: {flag_checks['deadline_agree']}/{scored}  (approximate: the label is a 3-day window)")
    if latencies:
        print(f"latency ms per call: median {statistics.median(latencies):.0f}  max {max(latencies)}  "
              f"tokens per call: median {statistics.median(tokens):.0f}")
    print("\nconfusion (label -> model): count")
    for (want, got), count in sorted(confusion.items()):
        if want != got:
            print(f"  {want} -> {got}: {count}")
    print(f"\nfirst {args.show_misses} misses (ticket, scenario, label, model):")
    for miss in misses[: args.show_misses]:
        print("  ", *miss)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())