# Proof Pipeline Dashboard

React dashboard for launching proof-pipeline runs and visualizing intermediate pipeline steps from JSON traces.

## What It Shows

- A form to launch a new pipeline run from the browser
- Live run status plus pipeline stdout/stderr
- Rewrite output text
- Skeleton compile results
- Per-admit fill attempts
- Raw model outputs, parse retries, and compiler feedback
- Final summary metrics for the current skeleton-and-fill pipeline

## Run

From `dashboard/`:

```powershell
pnpm install
pnpm dev:all
```

- UI: `http://localhost:5173`
- Trace API: `http://localhost:8787`

## Launching Runs

Open the dashboard and use **Start A Run**.

- **Formal theorem source** accepts either:
  - a full theorem header or source snippet, or
  - a bare proposition such as `forall n : nat, n + 0 = n.`
- **Informal proof** is the proof text the rewrite step consumes
- **Run label** is optional and is only used to name the temporary run artifacts

The dashboard backend creates a temporary theorem file, starts `pipeline/run.py`, and writes live trace data into `pipeline/traces/`.

## Browsing Existing Traces

You can still open any saved trace manually:

1. Click **Refresh Trace List**.
2. Select a trace.
3. Click **Open Trace**.

The dashboard now targets the current skeleton-and-fill trace format. Older transition-style traces are unsupported historical artifacts.
