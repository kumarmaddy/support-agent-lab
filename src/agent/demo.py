"""Walk one development ticket through the pipeline and print what each step did.

    python -m src.agent.demo --list 10
    python -m src.agent.demo --ticket T-000001 --model qwen2.5:7b

The demonstration uses the same pipeline as the evaluation runs. It reads no labels, writes no trace files and sends nothing to a
customer. It refuses the held-out split.
"""
import argparse
import textwrap
from pathlib import Path
from typing import Optional

from src.agent.model import ModelClient, OllamaClient
from src.agent.pipeline import Resolution, internal_guidance, run_ticket
from src.agent.prompting import load_prompt
from src.agent.run import check_not_heldout, warm_up
from src.agent.tools import Ticket, Toolbox
from src.kb.articles import load_articles

WIDTH = 100


def _wrap(text: str, indent: str = "    ") -> str:
    return "\n".join(textwrap.fill(line, WIDTH, initial_indent=indent, subsequent_indent=indent) if line.strip() else ""
                     for line in text.splitlines())


def _step_summary(step: dict) -> str:
    name, outcome = step["step"], step.get("outcome", "")
    if name == "read_ticket":
        reading = step.get("reading") or {}
        return (f"category={reading.get('category')}, deadline phrase={reading.get('deadline_phrase') or '-'}, "
                f"legal threat={reading.get('legal')}, order ids={reading.get('order_ids') or '-'}")
    if name == "decide":
        return f"{step['action']} because {step['reason']}" + (f" (article {step['article']})" if step.get("article") else "")
    if name == "draft_reply":
        rejected = step.get("rejected_drafts") or []
        return f"reply by {step['source']}" + (f"; rejected drafts: {', '.join(rejected)}" if rejected else "")
    return str(outcome)


def render(ticket: Ticket, resolution: Resolution) -> str:
    """Plain-text account of one run. Pure function of its inputs, so it can be tested without a model."""
    lines = [f"TICKET {ticket.ticket_id}   received {ticket.received_at[:10]} by {ticket.channel}   from {ticket.customer_email}",
             f"  Subject: {ticket.subject}", _wrap(ticket.body), "", "PIPELINE"]
    total = 0
    for step in resolution.steps:
        total += step["latency_ms"]
        model_part = f", {step['model_calls']} model call(s), {step['tokens_in']}+{step['tokens_out']} tokens" if step.get("model_calls") else ""
        lines.append(f"  {step['step']:<12} {step['latency_ms']:>6} ms{model_part}")
        lines.append(f"      {_step_summary(step)}")
    lines += ["", f"DECISION  {resolution.action}  ({resolution.reason})" + (f"  article {resolution.article}" if resolution.article else ""),
              f"REPLY (by {resolution.reply_source})", _wrap(resolution.reply), "", f"Total {total / 1000:.1f} s. Nothing was sent to a customer."]
    return "\n".join(lines)


def demo(box: Toolbox, model: ModelClient, ticket_id: str, kb: Path, reply_mode: str = "model") -> Optional[str]:
    got = box.get_ticket(ticket_id)
    if not got.ok:
        return None
    resolution = run_ticket(box, model, load_prompt("read_ticket", "v3"), load_prompt("reply", "v1"),
                            internal_guidance(load_articles(kb)), ticket_id, 0, reply_mode)
    return render(got.data, resolution)


def list_tickets(box: Toolbox, count: int) -> str:
    rows = box.conn.execute("SELECT ticket_id, subject FROM tickets ORDER BY ticket_id LIMIT ?", (count,)).fetchall()
    return "\n".join(f"{ticket_id}  {subject}" for ticket_id, subject in rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=Path("data/generated/dev/support.db"))
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p.add_argument("--model", default="llama3.2:3b")
    p.add_argument("--reply-mode", choices=["model", "template"], default="model")
    p.add_argument("--ticket", help="ticket id to run, for example T-000001")
    p.add_argument("--list", type=int, metavar="N", help="list the first N ticket ids and subjects, then stop")
    args = p.parse_args(argv)
    check_not_heldout(args.db)
    box = Toolbox.from_path(args.db)
    if args.list:
        print(list_tickets(box, args.list))
        return 0
    if not args.ticket:
        p.error("give --ticket TICKET_ID, or --list N to see some")
    model = OllamaClient(model=args.model)
    warm_up(model, load_prompt("read_ticket", "v3"))
    text = demo(box, model, args.ticket, args.kb, args.reply_mode)
    if text is None:
        print(f"No ticket {args.ticket} in {args.db}.")
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())