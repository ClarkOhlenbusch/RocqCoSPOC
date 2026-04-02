# Automated Proof Pipeline (Open Router)

This directory implements the automated proof pipeline: informal proof → strict Angelito → Rocq skeleton → iterative goal filling, using the OpenRouter API.

## Setup

1. API key — create `.env` in the repo root:

   ```bash
   OPENROUTER_API_KEY=sk-or-v1-...
   ```

2. Python — `pip install -r requirements.txt`

3. Rocq/Coq — ensure `coqc` is on PATH. The pipeline calls `scripts/check-target-proof.ps1`.

## Configuration

Edit `pipeline/config.yaml`:

- `rewrite_model` — model for informal → Angelito rewrite
- `skeleton_model` — model for Angelito → Rocq skeleton
- `fill_model` — model for filling each `admit.` sub-goal
- `max_fill_attempts` — compile-retry limit per sub-goal (default 3)
- `max_tokens`, `temperature` — generation defaults

## Usage

```powershell
python pipeline/run.py --informal path/to/informal.txt --formal path/to/formal.v --target coq/CongModEq.v
```

- `--informal`: text file with the informal proof
- `--formal`: file with the theorem statement
- `--target`: the `.v` file to write the proof into
- `--max-fill-attempts`: override retry limit per sub-goal
- `--trace-out`: custom JSON trace path

## What The Pipeline Does

1. **Rewrite** — Informal proof → strict Angelito syntax (PROVE, ASSUME, FACT, SIMPLIFY, THEREFORE, CONCLUDE, etc.)
2. **Skeleton** — Angelito → Rocq outer structure with `admit.` for each leaf goal. Compiles with `Admitted.`.
3. **Fill** — For each `admit.`, ask the model to produce replacement tactics using the Angelito proof as guidance and the available custom tactics. Compile after each fill. Retry with structured error feedback on failure.
4. **Trace** — JSON trace under `pipeline/traces/`.

## Prompt Files

| File | Purpose |
|------|---------|
| `prompts/01_rewrite.txt` | Informal → strict Angelito |
| `prompts/02a_skeleton.txt` | Angelito → Rocq skeleton with admits |
| `prompts/02b_fill_goal.txt` | Fill one admit with real tactics |
| `prompts/tactics_reference.md` | Available tactics for the model |

## Troubleshooting

- Skeleton doesn't compile: check that the formal statement is well-formed and the Angelito rewrite produced valid structure.
- Fill keeps failing: check the trace JSON for the exact Coq errors. The model may need a different tactic approach.
- API errors: verify `.env` has a valid `OPENROUTER_API_KEY`.
