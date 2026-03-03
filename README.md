# RocqCoSPOC — CoSProver-for-Coq Experimental Manual Workflow

A manual, experimental emulation of **CoSProver** ("Translating Informal Proofs into Formal Proofs Using a Chain of States") for Coq/Rocq. No Python pipeline or Coq REPL driver: you use **ChatGPT** for the rewrite, a **Gemini gem** for the chain of states (free), and an **IDE coding agent** for tactics; error feedback (ETR/ESR) happens naturally in the agent conversation.

**Reference:** CoSProver paper — *Translating Informal Proofs into Formal Proofs Using a Chain of States* (Lean); we adapt the pipeline to Coq and run it manually.

---

## Optional default state handoff (agent sees state on demand)

To avoid manual copy/paste of Coq state blocks, you can generate the current proof state from your cursor line with:

```powershell
.\scripts\get-proof-state.ps1 -FilePath <path-to-file> -CursorLine <line>
```

The repo also includes `.vscode/tasks.json`, which runs the same script with the current `${file}` and `${lineNumber}`.
Use that output as the `state_p` payload for prompt #3 (or #4/#5 when errors appear).

See [docs/AUTOMATED_STATE_PIPELINE.md](docs/AUTOMATED_STATE_PIPELINE.md) for the quick setup and workflow.

## The three-step process

1. **Rewrite** — Paste your informal proof into **ChatGPT** with prompt #1 ([docs/PROMPTS.md](docs/PROMPTS.md) or [prompts/01_rewrite.txt](prompts/01_rewrite.txt)). Copy the Coq-friendly proof.
2. **Chain of states** — Paste the formal statement and Coq-friendly proof into your **Gemini gem** (see [docs/GEMINI_GEM.md](docs/GEMINI_GEM.md)). Copy the state sequence.
3. **Tactics** — In your IDE, use the **coding agent** to apply tactics between adjacent states; paste prompts #3–#5 from [docs/PROMPTS.md](docs/PROMPTS.md) (or [prompts/](prompts/)) when you need tactic generation, ETR, or ESR.

---

## Where things live

| Item | Location |
|------|----------|
| Architecture & data flow | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Paper → our steps | [docs/PAPER_MAPPING.md](docs/PAPER_MAPPING.md) |
| All five prompts (copy-paste) | [docs/PROMPTS.md](docs/PROMPTS.md) |
| Gemini gem setup | [docs/GEMINI_GEM.md](docs/GEMINI_GEM.md) |
| Prompt templates (quick copy) | [prompts/](prompts/) — `01_rewrite.txt` … `05_esr.txt` |
| Few-shot examples for Gemini | [data/few_shot/](data/few_shot/) |

---

## Setup

- **Coq** (or Rocq) and an IDE with Coq support (e.g. VS Code + Coq extension, Proof General).  
  **→ Full steps:** [docs/SETUP_IDE.md](docs/SETUP_IDE.md) (install Rocq/Coq, VsRocq/VsCoq extension, set `vsrocq.path` in `.vscode/settings.json`, open this folder).
- **ChatGPT** (web) and **Gemini** (web or app) — no API keys required for this workflow.
- Optional: CoqHammer or manual tries with `lia`/`omega`/`auto` before asking the agent.

Run experiments by following the three steps above and iterating with ETR/ESR when Coq reports errors or the state doesn’t match the blueprint.
