# Proof Pipeline Prompts

Copy-paste these prompts into ChatGPT or your IDE agent. Replace the placeholders with your actual content.

## Prompt Index

| Name | Where | Placeholders |
|------|-------|--------------|
| Rocq-friendly rewrite with Angelito anchors | ChatGPT or another rewrite model | `{informal_proof}`, `{angelito_spec}` |
| Primary tactic generator | IDE coding agent | `{state_p}`, `{state_n}`, `{coq_friendly_proof}` |
| ETR | IDE agent when Rocq/Coq reports a tactic error | `{state_p}`, `{state_n}`, `{failed_tactics}`, `{error_message}`, `{coq_friendly_proof}` |
| ESR | IDE agent when the resulting proof state is not the intended one | `{state_a}`, `{state_b}`, `{state_c}`, `{coq_friendly_proof}` |

## Rocq-Friendly Rewrite With Angelito Anchors

Use in `ChatGPT` or another rewrite model.

```text
You are an expert mathematician and a master of the Coq/Rocq proof assistant. Your task is to rewrite an informal mathematical proof into a Rocq-friendly natural language proof that uses Angelito structural anchors from the provided specification.

Instructions:
1. Remove ambiguous terms like "similarly," "obviously," or "without loss of generality," and replace them with explicit logical steps.
2. Use `angelito-spec.md` as the authoritative source for Angelito keywords and proof-structure patterns.
3. Keep the output readable natural language, but add Angelito anchor lines wherever they apply, especially `ASSUME`, `GOAL`, `INDUCTION`, `FACT`, `THEREFORE`, and `CONCLUDE`.
4. Do not force a full `PROVE ... BEGIN ... END` block unless the structure is genuinely helpful; the default output should be a hybrid rewrite, not a pure Angelito program.
5. Explicitly state the proof structure being used using Angelito-compatible anchors when possible.
6. If a theorem, lemma, or previously established result is used, mark that step in a way consistent with the Angelito spec, typically through `FACT`, `APPLY`, or `BY`.
7. If the problem involves finite variable ranges, explicitly suggest exhaustive enumeration, as Coq solvers handle brute-force well.
8. If the proof involves basic arithmetic or linear integer inequalities, explicitly mention that the step follows from linear arithmetic.
9. Only use anchors that are justified by the actual proof structure.
10. Do not include meta commentary about the rewrite itself.
11. Output only the rewritten proof, with no summaries or compliance notes.
12. When an Angelito anchor applies, place it at the start of a line in uppercase form, for example `ASSUME:`, `GOAL:`, `INDUCTION`, `FACT:`, `THEREFORE:`, or `CONCLUDE:`.

Angelito Specification Reference:
{angelito_spec}

Input Informal Proof:
{informal_proof}

Output:
Provide the completely rewritten Rocq-friendly informal proof with Angelito structural anchors.
```

## Primary Tactic Generator

Use in the IDE coding agent.

````text
You are an expert in Coq/Rocq theorem proving. Your task is to analyze two given Coq proof states and generate the appropriate Ltac tactic(s) to transform from the initial state to the final state.

Follow these requirements:
1. Carefully examine both the initial and final states, identifying the exact changes needed.
2. Provide the minimal, most efficient Ltac sequence that would accomplish this transformation.
3. If the transformation requires multiple steps, combine them with line breaks or semicolons.
4. Do not include any text outside the code block.
5. "No Goals" refers to the end of the proof.
6. Use the Rocq-friendly proof as strategy guidance, but make sure the tactics are justified by the actual proof state.

Rocq-Friendly Proof Guidance:
{coq_friendly_proof}

Initial State:
{state_p}

Target Final State:
{state_n}

Output Format:
```coq
tactic1.
tactic2.
```
````

## ETR

Use in the IDE agent when Rocq/Coq reports a tactic or syntax error.

````text
You are an expert in Coq/Rocq theorem proving. Your task is to analyze two given Coq proof states and generate the appropriate Ltac tactic(s) to transform from the initial state to the final state, while considering previously attempted tactics and their error messages.

Instructions:
1. Carefully examine both the initial and final states, identifying the exact changes needed.
2. Review the previously attempted tactics and their error messages from the Coq compiler to avoid repeating mistakes.
3. Analyze why the error occurred, explain how the new tactic addresses the issue, and provide an improved tactic solution.
4. Use the Rocq-friendly proof as guidance for the intended proof strategy unless the current state shows that the plan needs to change.

Rocq-Friendly Proof Guidance:
{coq_friendly_proof}

Initial State:
{state_p}

Target Final State:
{state_n}

Previous Failed Attempt:
{failed_tactics}

Coq Error Message:
{error_message}

Output Format:
Analysis: [Your analysis of the error]
```coq
[Your corrected Ltac sequence]
```
````

## ESR

Use in the IDE agent when tactics succeed but the resulting proof state is not the intended target.

```text
I am working on a Coq/Rocq proof where we need to transform State A to State B. However, the current tactics only achieve a transformation from State A to State C.

Please analyze the proof context and:
1. Carefully examine both the current state (State C) and our actual target state (State B).
2. Identify what additional transformations are needed to bridge the gap between State C and State B.
3. Suggest the most appropriate Ltac sequence to complete the proof from State A all the way to State B.

Rocq-Friendly Proof Guidance:
{coq_friendly_proof}

State A (Starting Point):
{state_a}

State B (Actual Target):
{state_b}

State C (Current Result):
{state_c}

Output:
Please output the final working Ltac sequence inside triple backticks to get us from State A to State B. Include brief explanatory comments for each step.
```
