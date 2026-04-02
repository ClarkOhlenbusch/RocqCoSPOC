# Rocq Proof Pipeline

This repo contains an experimental Rocq/Coq proof pipeline that uses the Angelito pseudo-proof language as an intermediate representation between informal proofs and executable Rocq.

## Current workflow

1. **Rewrite** — Turn an informal proof into strict Angelito syntax (`PROVE`, `ASSUME`, `FACT`, `SIMPLIFY`, `THEREFORE`, `CONCLUDE`, etc.) using the [Angelito spec](angelito-spec.md).
2. **Skeleton** — Translate the Angelito proof's outer structure into Rocq with `admit.` placeholders for each leaf goal.
3. **Fill** — Iteratively fill each `admit.` with real tactics, compiling after each fill. On error, feed the structured error back and retry (up to 3 attempts per sub-goal).

The pipeline runs through [pipeline/run.py](pipeline/run.py) or can be done manually in your IDE.

## Key files

| Item | Location |
|------|----------|
| Angelito spec | [angelito-spec.md](angelito-spec.md) |
| Angelito → Rocq translation guide | [angelito-to-rocq.md](angelito-to-rocq.md) |
| Architecture and data flow | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Prompt templates | [prompts/](prompts/) |
| Tactics reference | [prompts/tactics_reference.md](prompts/tactics_reference.md) |
| IDE setup | [docs/SETUP_IDE.md](docs/SETUP_IDE.md) |
| Proof-state bridge | [docs/AUTOMATED_STATE_PIPELINE.md](docs/AUTOMATED_STATE_PIPELINE.md) |
| Automated pipeline | [pipeline/README.md](pipeline/README.md) |
| Example inputs | [data/examples/README.md](data/examples/README.md) |

## Setup

- Rocq/Coq plus an IDE with proof support. See [docs/SETUP_IDE.md](docs/SETUP_IDE.md).
- An LLM (ChatGPT, OpenRouter, etc.) for the rewrite/prove flow.
- Optional: an OpenRouter API key for the automated pipeline — see [pipeline/README.md](pipeline/README.md).
