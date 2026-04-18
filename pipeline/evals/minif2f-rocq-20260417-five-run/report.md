# miniF2F validation: five-case pipeline run (2026-04-17)

This run exercises the proof pipeline (`python pipeline/run.py`) on five distinct problems from the same **LLM4Rocq/miniF2F-rocq** validation slice used in `pipeline/evals/minif2f-rocq-20260415-104936/selection.json` (first five indices: 6, 26, 28, 35, 57).

## Configuration

- **Models** (all stages): `deepseek/deepseek-v3.2` — see `pipeline/config.yaml` at run time.
- **Retries**: `max_fill_attempts: 3`, `max_skeleton_attempts: 3`.
- **Artifacts per case**: `informal.txt`, `formal.v` (inputs), `target.v` (last written proof), `trace.json`, `trace-model-log.jsonl`, `pipeline.stdout.txt`, `pipeline.stderr.txt`.

## Summary

| Case ID | miniF2F index | Result | Failed stage |
|--------|-----------------|--------|----------------|
| `006-aime_1994_p4` | 6 | Failed | Skeleton compile |
| `026-mathd_numbertheory_84` | 26 | Failed | Fill (slot 1) |
| `028-mathd_algebra_37` | 28 | Failed | Fill (slot 1) |
| `035-mathd_numbertheory_200` | 35 | Failed | Skeleton format |
| `057-imo_1966_p5` | 57 | Failed | Skeleton compile |

None of the five runs produced a fully checked `Qed.` proof in this session.

## Per-case notes

### 006 — `aime_1994_p4`

- **Rewrite**: Succeeded on the second format attempt (first attempt was rejected for pseudo-math such as sigma-style notation).
- **Skeleton**: After format fixes, the scaffold **did not compile**: Coq reported a **type mismatch** (`nat` vs `Z`) in the generated `assert` context (see `trace.json` → last skeleton `check_stderr`).
- **Fill**: Not started — pipeline refuses fill retries when the admitting scaffold does not compile.

### 026 — `mathd_numbertheory_84`

- **Rewrite / skeleton**: Angelito and a compiling admit-scaffold were produced (skeleton compile succeeded on a later attempt after earlier outputs violated “outer structure only” rules).
- **Fill**: Failed on the **first** admit with a **fill model error**: all three format-validation paths failed — Angelito-style `simplify` without `Angelito` imports, then `field` without visible field imports, then raw output that did not parse as a valid tactic block for the pipeline’s extractor.

### 028 — `mathd_algebra_37`

- **Rewrite / skeleton**: Rewrite parsed; skeleton eventually **compiled** with admits.
- **Fill**: **Three compile-time failures** on slot 1 — the model kept emitting high-level `simplify lhs ...` Angelito tactics while the generated `formal.v` / target did not import `Angelito.Ltac1`, so validator rejected the fills before a successful compile.

### 035 — `mathd_numbertheory_200`

- **Skeleton**: **Model error** after three skeleton attempts — the model repeatedly emitted `simplify lhs (...) by admit.`, which violates the rule that `admit.` must appear as a **standalone** placeholder line, not embedded in another tactic.

### 057 — `imo_1966_p5`

- **Rewrite**: One rewrite attempt failed (missing final `END`); a later attempt parsed.
- **Skeleton**: Scaffold **did not compile** after retries — Coq error **`x is already used`** (duplicate binder in generated proof script), so fill was not attempted.

## Where to look next

For each case, the authoritative detail is:

- `cases/<case-id>/trace.json` — stage timings, errors, skeleton compile attempts, fill attempts.
- `cases/<case-id>/trace-model-log.jsonl` — raw OpenRouter responses.

Root selection for this folder: `selection.json`.
