# Autonomous CoS Pipeline (Open Router)

This directory implements the autonomous CoSProver-style pipeline: informal proof → Coq-friendly rewrite → Chain of States → tactic generation with ETR/ESR, using the Open Router API and free models.

## Setup

1. **API key**  
   Create a `.env` file in the repository root with:
   ```bash
   OPENROUTER_API_KEY=sk-or-v1-...
   ```
   Do not commit `.env` (it is in `.gitignore`).

2. **Python**  
   From the repo root:
   ```bash
   pip install -r requirements.txt
   ```

3. **Coq**  
   The pipeline calls `scripts/check-target-proof.ps1` and `scripts/get-proof-state.ps1`. Ensure Coq is on PATH or configured in `.vscode/settings.json` / `scripts/check-proofs.ps1`.

## Configuration

Edit `pipeline/config.yaml` to change models or limits:

- **Models** (all free-tier by default):
  - `rewrite_model`, `cos_model`: rewrite and Chain of States
  - `tactic_model`, `etr_model`, `esr_model`: tactics and error recovery (DeepSeek R1 to match the paper)
- **Limits**: `max_tactic_errors`, `max_state_mismatch` — max retries per transition for tactic errors and state mismatch.
- **Generation**: `max_tokens`, `temperature`.

## Usage

Run from the **repository root**. Use **actual file paths** (do not type angle brackets in PowerShell—they are redirection operators).

```powershell
python pipeline/run.py --informal path/to/informal.txt --formal path/to/formal.v --target coq/CongModEq.v
```

Example:

```powershell
python pipeline/run.py --informal data/informal.txt --formal coq/CongModEq.v --target coq/CongModEq.v
```

See **`data/examples/README.md`** for ready-made examples (simple equality and inequality) and exact commands.

- **`--informal`**: Text file containing the informal proof.
- **`--formal`**: File containing the Coq theorem statement (or the same target file if it already has the statement and `Proof.`).
- **`--target`**: The `.v` file to edit. It must already contain a theorem and a `Proof.` line; the pipeline appends tactics and optionally adds `Proof.` if the file has content but no proof block.
- **`--max-etr`**, **`--max-esr`**: Override config retry limits per transition.

The pipeline will:

1. Rewrite the informal proof (Coq-friendly).
2. Generate a Chain of States from the formal statement and Coq-friendly proof.
3. For each adjacent state pair, generate tactics, append them to the target file, run `check-target-proof.ps1`; on Coq error, run ETR and replace the last block; on success, run `get-proof-state.ps1` and compare to the expected state; on mismatch, run ESR and replace the last block.
4. Print a summary (transitions, ETR/ESR counts).

All configured models are free-tier where possible (e.g. `deepseek/deepseek-r1:free`).

## Troubleshooting

- **404 Not Found:** The client now prints Open Router’s response body. If you see 404, check that your API key is valid at [Open Router Keys](https://openrouter.ai/keys) and that you can reach `https://openrouter.ai/api/v1/chat/completions` (e.g. from a browser or `curl`). Corporate proxies or firewalls can sometimes block or alter requests.
- **401/403:** Invalid or missing `OPENROUTER_API_KEY`. Ensure `.env` is in the repo root and contains `OPENROUTER_API_KEY=sk-or-v1-...`.
