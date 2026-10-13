# Phase 4 Held-out Run Runbook

| Item | Value |
|---|---|
| Stage | 4.2 (freeze and held-out run kit) |
| Governs | Criteria in `phase-4-design-and-acceptance.md` v1.0 (approved 2026-10-12) |
| Where | Windows PowerShell, repository root `C:\Users\kumar\source\repos\support-agent-lab` |

The gate is `python -m src.evaluation.heldout`. The ordinary runner and scorer still refuse the held-out split; they are unchanged.

## Rules while you work through this

- Do not edit any file under `src\`, `config\`, `data\seed\kb\` or `data\security\` after Step 3. The gate refuses to run if one changes.
- Do not regenerate the held-out data. Do not open `data\labels\heldout\labels.jsonl` or the held-out database.
- One scored run per model. If the 7B run is interrupted, follow "If a run is interrupted" below.
- Paste console output exactly as printed. Do not edit it.

## Step 1. Apply the stage 4.2 files and check

1. Copy the stage 4.2 files to the repo paths in the delivery table.
2. Add these lines to `.gitignore` if they are not there yet (the security run folders and the registry live under ignored paths): `data/security/runs/`. (`data/audit/` and `data/runs/` are already ignored.)
3. Clear caches and run the tests:

```powershell
Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
python -m pytest -q
```

Expected: 1163 passed.

## Step 2. Confirm the Phase 3 tag and the dataset

```powershell
git tag --list "phase-*"
python -m src.datagen.freeze verify
```

If `phase-3-complete` is not listed, find the last Phase 3 commit (stage 3.9) and tag it:

```powershell
git log --oneline -12
git tag phase-3-complete 1234abc
```

Replace `1234abc` with the hash of the stage 3.9 commit. Expected from the second command: the dataset verification passes for both splits.

## Step 3. Commit, then create the freeze record

```powershell
git add -A
git commit -m "feat(eval): add held-out gate and freeze record tooling (stage 4.2)"
git status --short
python -m src.evaluation.heldout create
```

`git status --short` must print nothing. The `create` command refuses a dirty tree. It prints the commit, the number of files, 150 held-out tickets and the record digest. Then:

```powershell
git add docs/evidence/phase-4-freeze-record.json
git commit -m "docs(evidence): add Phase 4 freeze record"
git tag phase-4-frozen
python -m src.evaluation.heldout check
git push origin main --tags
```

Expected from `check`: "The freeze holds". Send me the output of `create` and `check`.

## Step 4. Prepare the machine for the 7B run

- Ollama is running, with `qwen2.5:7b` and `nomic-embed-text` pulled (`ollama list`).
- Plug in the laptop, set the power plan to best performance, close heavy applications and stop other model runs.
- Expect about 50 minutes (dev run median was 17.8 s per ticket, 150 tickets).

## Step 5. The 7B run (once)

```powershell
python -m src.evaluation.heldout run --tag 7b
```

It prints one line per ticket and finishes with "held-out run recorded: run-...". Note the run folder name. If Ollama is not running, the command stops before using the run, and you can start it again normally.

## Step 6. Score and verify

```powershell
python -m src.evaluation.heldout score data\runs\run-YYYYMMDD-HHMMSS-xxxxxx
python -m src.audit --log data\audit\heldout-7b.jsonl --verify
```

Use the exact run folder printed in Step 5. Paste both outputs to me, plus the run summary printed at the end of Step 5.

## Step 7. The 3B run (descriptive, decision D2)

```powershell
python -m src.evaluation.heldout run --tag 3b
python -m src.evaluation.heldout score data\runs\run-YYYYMMDD-HHMMSS-yyyyyy
```

Use the folder printed by the 3B run. Paste the output as above.

## Step 8. Keep the registry as evidence

```powershell
Copy-Item data\audit\heldout-registry.json docs\evidence\phase-4-heldout-registry.json
git add docs/evidence/phase-4-heldout-registry.json
git commit -m "docs(evidence): record held-out runs" 
```

Stage 4.3 starts from your pasted output.

## If a run is interrupted

| Situation | What happens | What to do |
|---|---|---|
| Ollama not running, or the command fails before any ticket | The single run is not used | Fix it and run the same command again |
| Crash or power cut after tickets started | The registry keeps the entry as `started` and the same command is refused | Do not change anything. Run `python -m src.evaluation.heldout check`; if it holds, run the same command with `--rerun-reason "what happened"`. The reason is recorded and reported. |
| `check` reports a changed file | The held-out split stays closed | Do not fix it by editing. Tell me which file; the options are restoring it with git, or recording that the freeze was broken |

## What the gate does and does not prove

It proves that the code, prompts, policy, knowledge base, injection cases and held-out files used for the run are the files in the record, that each model was run once (or with a recorded reason), and that scoring used a run made on the frozen held-out database. It does not prove the machine was idle or that you did not look at the held-out data. Those rest on the rules above.