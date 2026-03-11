# CoS Pipeline Dashboard

Simple React dashboard for visualizing intermediate pipeline steps from JSON traces.

## What It Shows

- Rewrite output text
- Parsed Chain-of-States blocks
- Per-transition attempts
- ETR / ESR retries and errors
- Final summary metrics

## Run

From `dashboard/`:

```powershell
pnpm install
pnpm dev:all
```

- UI: `http://localhost:5173`
- Trace API: `http://localhost:8787`

## Generate Trace Data

From repository root, run the pipeline. It now writes trace JSON files to `pipeline/traces/` by default:

```powershell
python pipeline/run.py --informal data/examples/01_simple_eq/informal.txt --formal data/examples/01_simple_eq/formal.v --target coq/Example.v
```

Optional custom trace path:

```powershell
python pipeline/run.py ... --trace-out pipeline/traces/my-run.json
```

Then open the dashboard, click **Refresh Trace List**, select a trace, and click **Open Trace**.
