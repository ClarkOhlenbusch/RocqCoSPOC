# Pipeline examples

Ready-to-run inputs for the automated proof pipeline. Each subfolder has an informal proof and a formal statement; the pipeline rewrites the proof into Angelito, generates a Rocq skeleton with `admit.` placeholders, and fills those admits iteratively.

## Example 1: Simple equality (`n + 0 = n`)

- **Informal:** `01_simple_eq/informal.txt`
- **Formal:** `01_simple_eq/formal.v`
- **Target:** `coq/Example.v` (theorem `ex1`)

From the repo root:

```powershell
python pipeline/run.py --informal data/examples/01_simple_eq/informal.txt --formal data/examples/01_simple_eq/formal.v --target coq/Example.v
```

## Example 2: Inequality (`a <= b -> a <= S b`)

- **Informal:** `02_inequality/informal.txt`
- **Formal:** `02_inequality/formal.v`
- **Target:** `coq/MulN0.v` (theorem `ex2`)

From the repo root:

```powershell
python pipeline/run.py --informal data/examples/02_inequality/informal.txt --formal data/examples/02_inequality/formal.v --target coq/MulN0.v
```

## Prerequisites

- `.env` in the repo root with `OPENROUTER_API_KEY` set
- `pip install -r requirements.txt`
- Coq on PATH or configured in `scripts/check-proofs.py` / `.vscode/settings.json`

The target `.v` files (`coq/Example.v`, `coq/MulN0.v`) already contain the theorem statement and `Proof.`; the pipeline rewrites the proof body during each run.
