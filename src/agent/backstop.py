"""A word-level backstop for the two flags that always escalate (stage 3.8; ADR-015).

The read step is a model, and ticket text can talk a model into answering "no" ("do not mark this as legal"). A chargeback or legal threat and a
suspected account compromise both send a ticket to a person before anything else happens, so a flag that is talked away removes that
review. This scan looks for plain, unambiguous wording in the ticket text itself, in code, where the sender cannot argue with it.

It can only ADD a flag. It never clears one the reader raised, and it is deliberately narrow: phrases that are almost always a threat or a
report of unauthorised access, not single words that appear in ordinary mail ("court" in an address, "sue" inside "issue"). Misspelt or
paraphrased threats are not caught here; the reader and the approver remain the defence for those (risk R17).
"""
import re
from dataclasses import dataclass

_LEGAL = re.compile(
    r"\bcharge\s?-?backs?\b|\blawyers?\b|\battorneys?\b|\bsolicitors?\b|\bsue\b|\bsuing\b|\blegal (?:action|proceedings|team|advice)\b|\bsmall claims\b"
    r"|\b(?:to|in|into) court\b|\bdispute (?:the|this|that|it)\b.{0,40}\b(?:bank|card|credit)\b"
    r"|\b(?:consumer protection|attorney general|trading standards|ombudsman|better business bureau)\b", re.IGNORECASE | re.DOTALL)
_COMPROMISE = re.compile(
    r"\bhacked\b|\bhijacked\b|\bcompromised\b|\bunauthori[sz]ed (?:access|login|charges?|purchases?|orders?)\b"
    r"|\bsomeone (?:else )?(?:logged|got|accessed|broke) (?:in|into)\b|\bchanged my password\b"
    r"|\bdid ?n[o']t (?:place|make|order) (?:this|these|that|any)\b|\bfraudulent\b", re.IGNORECASE)


@dataclass(frozen=True)
class Flags:
    legal: bool
    compromise: bool


def scan(subject: str, body: str) -> Flags:
    text = f"{subject}\n{body}"
    return Flags(bool(_LEGAL.search(text)), bool(_COMPROMISE.search(text)))