# Paper Mapping: CoSProver → Coq Experimental Workflow

Short reference mapping the CoSProver paper (Lean) to our manual Coq emulation.

---

## Paper sections / appendix → our steps

| Paper / appendix | Our step | Our artifact |
|------------------|----------|--------------|
| Preprocessing: rewrite informal → Lean-friendly | Step 1: Coq-friendly rewrite | Prompt #1 → ChatGPT web UI → Coq-friendly proof text |
| Appendix A.3: Prompt for Chain of States Generator | Step 2: Chain of States | Prompt #2 → Gemini gem → state chain (Coq REPL format) |
| Primary tactic generation (adjacent states) | Step 3: Tactic generation | Prompt #3 → IDE agent → Ltac in `.v` file |
| Appendix B: Prompt for Error Recovery / Revised Tactic Generation | ETR | Prompt #4 → IDE agent when Coq reports tactic error |
| Appendix B: Prompt for State Renewal and Completion | ESR | Prompt #5 → IDE agent when state doesn’t match blueprint |

---

## Prompts → files

| Prompt | Paper reference | Our file(s) |
|--------|-----------------|-------------|
| #1 Coq-friendly rewrite | Preprocessing (adapted) | `docs/PROMPTS.md`, `prompts/01_rewrite.txt` |
| #2 CoS generator | Appendix A.3 (Coq state format) | `docs/PROMPTS.md`, `prompts/02_chain_of_states.txt` |
| #3 Primary tactic generator | Appendix B (Primary Tactic Generation) | `docs/PROMPTS.md`, `prompts/03_tactic_generator.txt` |
| #4 ETR | Appendix B (Error Recovery) | `docs/PROMPTS.md`, `prompts/04_etr.txt` |
| #5 ESR | Appendix B (State Renewal) | `docs/PROMPTS.md`, `prompts/05_esr.txt` |

---

## What we do not implement

- Fine-tuned CoS generator (paper: 7B model + Leanjixia / elaboration trees). We use a **Gemini gem** with few-shot prompting instead.
- Automated Coq REPL / verifier. Verification is done by editing the `.v` file and running Coq in the IDE; the **IDE coding agent** gets errors directly.
- Common-tactic prover or CoqHammer in front of the agent. Optional: you can try `lia`, `omega`, `auto` or CoqHammer yourself before asking the agent.
