# Angelito Tactics Reference (for LLM prompts)

This file lists the custom tactics available when `From Angelito Require Import Tactics.` is loaded,
plus the standard Coq tactics used in this project.

## Custom Angelito Tactics

| Tactic | Purpose | Example |
|--------|---------|---------|
| `assume x : T.` | Introduce a variable/hypothesis (like `intros x`) | `assume n : nat.` |
| `simplify rhs EXPR using ltac:(TACTIC).` | Simplify the right-hand side of an equation | `simplify rhs x = y using ltac:(rewrite lemma1).` |
| `simplify lhs EXPR using ltac:(TACTIC).` | Simplify the left-hand side of an equation | `simplify lhs x = y using ltac:(rewrite lemma1, lemma2).` |

## Standard Coq Tactics (whitelist for this project)

| Tactic | Purpose |
|--------|---------|
| `intros x y H.` | Introduce variables and hypotheses |
| `assert (H : PROP). { proof. }` | Prove an intermediate claim |
| `apply lemma.` | Apply a lemma to the current goal |
| `exact term.` | Provide an exact proof term |
| `rewrite lemma.` / `rewrite <- lemma.` | Rewrite using an equality |
| `replace A with B by ring.` | Algebraic rearrangement |
| `destruct H as [x Hx].` | Case split or unpack existential |
| `exists witness.` | Provide witness for existential |
| `induction n.` | Structural induction |
| `lia.` | Linear integer arithmetic (nat and Z) |
| `nia.` | Nonlinear integer arithmetic |
| `ring.` | Ring equalities |
| `auto.` | Basic automation |
| `split.` | Split conjunction goal |
| `left.` / `right.` | Choose disjunct |
| `unfold def.` | Unfold a definition |
| `simpl.` | Simplify expressions |
| `reflexivity.` | Prove `x = x` |
| `symmetry.` | Swap sides of an equality |
| `admit.` | Placeholder (proof incomplete) |

## DO NOT USE

| Tactic | Reason |
|--------|--------|
| `linarith` | Not loaded — use `lia` |
| `omega` | Deprecated — use `lia` |
| `ring_nf` | Not available |
| `change` for algebra | Only definitional equality — use `replace ... by ring` |
| `have H : T := by` | Lean syntax — use `assert` |

## Angelito Keyword → Rocq Mapping

| Angelito | Rocq |
|----------|------|
| `ASSUME x : T` | `intros x.` or `assume x : T.` |
| `SIMPLIFY RHS expr [BY l1, l2]` | `simplify rhs expr using ltac:(rewrite l1, l2).` |
| `SIMPLIFY LHS expr [BY l1, l2]` | `simplify lhs expr using ltac:(rewrite l1, l2).` |
| `FACT h: stmt [BY lemma]` | `assert (h : stmt). { apply lemma. }` |
| `FACT h: stmt [BY lemma a1 a2]` | `assert (h : stmt). { exact (lemma a1 a2). }` |
| `APPLY theorem SPLIT INTO` | `apply theorem.` then bullets for subgoals |
| `THEREFORE conclusion [BY h1]` | `exact h1.` or `apply ... ; exact h1.` |
| `CONCLUDE` | (all goals discharged) |
| `INDUCTION n` | `induction n.` |
| `SINCE condition` | `assert (h : condition). { ... }` |
| `FOR_ALL x ∈ set` | `intros x hx.` |
| `WITNESS_AT idx` | `exists idx.` |
