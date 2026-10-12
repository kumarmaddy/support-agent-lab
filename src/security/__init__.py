"""The injection and misuse suite (phase-3-design.md, section 5.7; stage 3.8).

A fixed, deterministic set of attack and control cases (``data/security/cases.jsonl``), a runner that applies each case to the real code
in a throw-away world, and a scorer that judges the outcome from the observed state alone. Nothing here calls a real model.
"""