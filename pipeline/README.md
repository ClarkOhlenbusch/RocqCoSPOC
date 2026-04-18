# Automated Proof Pipeline

This directory implements the current proof pipeline:

1. Informal proof -> strict Angelito
2. Angelito -> Rocq skeleton / slot template
3. Per-slot model fills with compile feedback in the loop

It uses the OpenRouter API for model calls.

## Setup

1. Create `.env` in the repo root:

   ```bash
   OPENROUTER_API_KEY=sk-or-v1-...
   ```

2. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Ensure `coqc` is on PATH. The pipeline calls `scripts/check-target-proof.py`.

## Configuration

Edit `pipeline/config.yaml`:

- `rewrite_model`: model or ordered fallback list for informal -> Angelito
- `skeleton_model`: model or ordered fallback list for Angelito -> Rocq skeleton
- `fill_model`: model or ordered fallback list for per-slot tactic generation
- `max_fill_attempts`: compile-retry limit per slot
- `max_tokens`, `temperature`: generation defaults
- `request_retries`, `request_backoff_*`: transient OpenRouter retry/backoff controls

Pin explicit model IDs when possible. `openrouter/free` is useful for experimentation, but it is less reproducible than stage-specific pinned models.

## Usage

```powershell
python pipeline/run.py --informal path/to/informal.txt --formal path/to/formal.v --target coq/CongModEq.v
```

- `--informal`: text file with the informal proof
- `--formal`: file with the theorem statement
- `--target`: the `.v` file to write
- `--max-fill-attempts`: override compile retries per slot
- `--trace-out`: custom JSON trace path

## What It Does

1. Rewrite emits strict Angelito only.
2. Skeleton builds a Rocq scaffold with named Jinja2 slots.
3. The skeleton stage asks the model to preserve the proof scaffold from Angelito, including useful direct-proof checkpoints such as intermediate `FACT` / `THEREFORE` steps translated into Rocq `assert` / `destruct` scaffolding with `admit.` leaves.
4. Each slot is rendered first as `admit.` to capture the goal state.
5. The model generates only the tactic block for the current slot.
6. The pipeline renders that tactic block into the template, recompiles, and retries on failure.

## Outputs

Each run writes:

- A JSON trace under `pipeline/traces/`
- A sibling `*-model-log.jsonl` file with every raw OpenRouter response for the run

## Prompt Files

| File | Purpose |
|------|---------|
| `prompts/01_rewrite.txt` | Informal -> strict Angelito |
| `prompts/02a_skeleton.txt` | Angelito -> Rocq skeleton / slot scaffold |
| `prompts/02b_fill_goal.txt` | Fill one slot with real tactics |
| `prompts/tactics_reference.md` | Available tactics for the model |

## Troubleshooting

- Skeleton fails: inspect the trace to see whether the model invented structure that was not present in the Angelito proof.
- Fill fails: inspect both the trace JSON and the sibling `*-model-log.jsonl` file.
- API failures: verify `OPENROUTER_API_KEY` and consider pinning specific model IDs.
