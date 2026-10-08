"""Evaluation of pipeline runs against the development labels.

Scoring is separate from running: the runner never sees labels, and this package reads only files a run has already written.
The agent package must not import it (a test enforces this). The held-out split is refused here as well as in the runner.
"""