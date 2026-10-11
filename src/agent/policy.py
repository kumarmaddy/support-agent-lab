"""Policy engine (phase-3-design.md, section 5.1; stage 3.2).

A pure function decides what may happen to an action the agent proposes: ``evaluate(request, policy) -> PolicyDecision``. It reads no
database and calls no model. The rules live in ``config/policy.toml`` (standard-library ``tomllib``), are validated when loaded, and the
file's sha256 is carried in every decision, so a decision can be traced to the exact rules that produced it.

Outcomes, in the order they are checked: ``deny`` (the action is not allowed), ``require_approval`` (a person approves it first, in the
standard or the senior queue), ``auto_execute`` (allowed without a person; ships switched off). The first matching rule wins; inside one
outcome the order of the file decides. When nothing matches the action needs approval: the engine fails closed.
"""
import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DENY, REQUIRE_APPROVAL, AUTO_EXECUTE = "deny", "require_approval", "auto_execute"
OUTCOMES = (DENY, REQUIRE_APPROVAL, AUTO_EXECUTE)          # also the order in which they are checked
STANDARD, SENIOR = "standard", "senior"
QUEUES = (STANDARD, SENIOR)
DEFAULT_RULE_ID = "DEFAULT-APPROVAL"

# The actions the policy knows (the proposals the pipeline can make).
ACTIONS = ("cancel_order", "change_address", "return_label", "exchange", "replacement", "refund")

DEFAULT_POLICY_PATH = Path("config/policy.toml")


class PolicyError(Exception):
    """The policy file cannot be used. A run must not start on a policy it cannot read."""


@dataclass(frozen=True)
class PolicyRequest:
    """What the policy is asked about. ``None`` means the value is unknown; a numeric condition on an unknown value does not match."""
    action: str
    reason: str = ""                                    # the pipeline's reason for the proposal, for the record
    amount_cents: Optional[int] = None
    payment_amount_cents: Optional[int] = None
    payment_already_refunded: Optional[bool] = None
    customer_tier: Optional[str] = None
    order_age_days: Optional[int] = None
    prior_refunds: Optional[int] = None
    legal_flag: bool = False
    compromise_flag: bool = False                       # the reader suspects the account was accessed by someone else (stage 3.3)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    outcome: str
    reason: str
    queue: str
    when: dict


@dataclass(frozen=True)
class Policy:
    version: str
    auto_execute_enabled: bool
    rules: tuple
    sha256: str


@dataclass(frozen=True)
class PolicyDecision:
    outcome: str
    rule_id: str
    reason: str
    queue: str                                          # which approval queue; "standard" when no approval applies
    evidence: dict = field(default_factory=dict)        # the request values the matching conditions used
    policy_sha256: str = ""
    policy_version: str = ""

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "rule_id": self.rule_id, "reason": self.reason, "queue": self.queue,
                "evidence": dict(self.evidence), "policy_sha256": self.policy_sha256, "policy_version": self.policy_version}


# ------------------------------------------------------------------ conditions
# key -> (kind, request field). "list" keys match when the field is one of the listed strings; "gte"/"lte" compare an integer;
# "flag" keys match when the field equals the stated boolean.
def _exceeds(r: PolicyRequest):
    if r.amount_cents is None or r.payment_amount_cents is None:
        return None
    return r.amount_cents > r.payment_amount_cents


CONDITIONS = {
    "action": ("list", lambda r: r.action),
    "reason": ("list", lambda r: r.reason),
    "customer_tier": ("list", lambda r: r.customer_tier),
    "amount_cents_gte": ("gte", lambda r: r.amount_cents),
    "amount_cents_lte": ("lte", lambda r: r.amount_cents),
    "order_age_days_gte": ("gte", lambda r: r.order_age_days),
    "order_age_days_lte": ("lte", lambda r: r.order_age_days),
    "prior_refunds_gte": ("gte", lambda r: r.prior_refunds),
    "amount_exceeds_payment": ("flag", _exceeds),
    "payment_already_refunded": ("flag", lambda r: r.payment_already_refunded),
    "legal_flag": ("flag", lambda r: r.legal_flag),
    "compromise_flag": ("flag", lambda r: r.compromise_flag),
}
RULE_KEYS = {"id", "outcome", "reason", "queue", "when"}
ENGINE_KEYS = {"version", "auto_execute_enabled"}
TOP_KEYS = {"engine", "rule"}


def _validate_when(rule_id: str, when) -> dict:
    if not isinstance(when, dict) or not when:
        raise PolicyError(f"rule {rule_id}: 'when' must be a table with at least one condition")
    for key, value in when.items():
        if key not in CONDITIONS:
            raise PolicyError(f"rule {rule_id}: unknown condition {key!r}")
        kind = CONDITIONS[key][0]
        if kind == "list":
            if not (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
                raise PolicyError(f"rule {rule_id}: {key} must be a non-empty list of strings")
            if key == "action" and not set(value) <= set(ACTIONS):
                raise PolicyError(f"rule {rule_id}: unknown action in {value}")
        elif kind in ("gte", "lte"):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PolicyError(f"rule {rule_id}: {key} must be a whole number of zero or more")
        elif not isinstance(value, bool):
            raise PolicyError(f"rule {rule_id}: {key} must be true or false")
    return dict(when)


def parse_policy(raw: bytes) -> Policy:
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"policy file cannot be parsed: {exc}") from exc
    if set(data) - TOP_KEYS:
        raise PolicyError(f"unknown section(s): {sorted(set(data) - TOP_KEYS)}")
    engine = data.get("engine", {})
    if set(engine) - ENGINE_KEYS:
        raise PolicyError(f"unknown engine key(s): {sorted(set(engine) - ENGINE_KEYS)}")
    version, switch = engine.get("version"), engine.get("auto_execute_enabled", False)
    if not isinstance(version, str) or not version:
        raise PolicyError("engine.version must be a non-empty string")
    if not isinstance(switch, bool):
        raise PolicyError("engine.auto_execute_enabled must be true or false")
    rules, seen = [], set()
    for index, item in enumerate(data.get("rule", []), 1):
        rule_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(rule_id, str) or not rule_id:
            raise PolicyError(f"rule number {index} has no id")
        if rule_id in seen or rule_id == DEFAULT_RULE_ID:
            raise PolicyError(f"rule id {rule_id} is duplicated or reserved")
        seen.add(rule_id)
        if set(item) - RULE_KEYS:
            raise PolicyError(f"rule {rule_id}: unknown key(s) {sorted(set(item) - RULE_KEYS)}")
        if item.get("outcome") not in OUTCOMES:
            raise PolicyError(f"rule {rule_id}: outcome must be one of {OUTCOMES}")
        if not isinstance(item.get("reason"), str) or not item["reason"]:
            raise PolicyError(f"rule {rule_id}: a reason is required")
        queue = item.get("queue", STANDARD)
        if queue not in QUEUES:
            raise PolicyError(f"rule {rule_id}: queue must be one of {QUEUES}")
        if "queue" in item and item["outcome"] != REQUIRE_APPROVAL:
            raise PolicyError(f"rule {rule_id}: only a require_approval rule has a queue")
        rules.append(Rule(rule_id, item["outcome"], item["reason"], queue, _validate_when(rule_id, item.get("when"))))
    return Policy(version, switch, tuple(rules), hashlib.sha256(raw).hexdigest())


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> Policy:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise PolicyError(f"policy file cannot be read: {exc}") from exc
    return parse_policy(raw)


# ------------------------------------------------------------------ evaluation
def _matches(rule: Rule, request: PolicyRequest) -> Optional[dict]:
    """The evidence (request values) when every condition holds, otherwise None."""
    evidence = {}
    for key, expected in rule.when.items():
        kind, get = CONDITIONS[key]
        value = get(request)
        if value is None:
            return None
        if kind == "list":
            ok = value in expected
        elif kind == "gte":
            ok = value >= expected
        elif kind == "lte":
            ok = value <= expected
        else:
            ok = value is expected
        if not ok:
            return None
        evidence[key] = value
    return evidence


def evaluate(request: PolicyRequest, policy: Policy) -> PolicyDecision:
    """Pure: the same request and rules always give the same decision."""
    stamp = {"policy_sha256": policy.sha256, "policy_version": policy.version}
    for outcome in OUTCOMES:
        for rule in policy.rules:
            if rule.outcome != outcome:
                continue
            evidence = _matches(rule, request)
            if evidence is None:
                continue
            if outcome == AUTO_EXECUTE and not policy.auto_execute_enabled:
                return PolicyDecision(REQUIRE_APPROVAL, rule.rule_id, rule.reason + " (auto-execute is switched off, so a person approves)",
                                      STANDARD, {**evidence, "auto_execute_enabled": False}, **stamp)
            return PolicyDecision(outcome, rule.rule_id, rule.reason, rule.queue, evidence, **stamp)
    return PolicyDecision(REQUIRE_APPROVAL, DEFAULT_RULE_ID, "No rule matched, so a person approves (fail closed).", STANDARD,
                          {"action": request.action}, **stamp)