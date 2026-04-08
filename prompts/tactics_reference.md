# Angelito Ltac1 Tactics Reference

This file defines the tactic vocabulary that prompt templates may mention.

## Required Imports

These high-level tactics are available only when the proof source contains:

```coq
From RocqCoSPOC Require Import Angelito.
Import Angelito.Ltac1.
```

## High-Level Tactics

These are the only high-level Angelito tactics the model should emit directly.

| Tactic | Purpose | Structured feedback |
|--------|---------|---------------------|
| `assert_goal (expr).` | Check that the current goal exactly matches `expr` | `Expected goal: ... Got: ...` |
| `simplify lhs (a = b). { tac. }` | Rewrite the left-hand side from `a` to `b` using an explicit proof block | `assert_lhs: Expected LHS: ... but got: ...` |
| `simplify rhs (a = b). { tac. }` | Rewrite the right-hand side from `a` to `b` using an explicit proof block | `assert_rhs: Expected RHS: ... but got: ...` |
| `simplify lhs (a = b) by tac.` | Same left-hand-side rewrite with a one-line justification tactic | same |
| `simplify rhs (a = b) by tac.` | Same right-hand-side rewrite with a one-line justification tactic | same |
| `pick x : T.` | Introduce one binder with type checking | `pick (...): Unexpected type got: ...` |
| `pick x : T, y : U, ... .` | Introduce multiple binders with type checking | same |

## Usage Examples

These examples are copied from the checked-in `Angelito.v` tests and should be treated as canonical syntax:

```coq
assert_goal (2 = 1).
```

```coq
simplify rhs (1 = 0 + 1). { reflexivity. }
assert_goal (2 = 0 + 1).
```

```coq
simplify lhs (1 + 1 = 2) by reflexivity.
assert_goal (2 = 1).
```

```coq
pick x : nat, y : bool.
assert_goal (if y then x = 1 else x = 0).
```

## Standard Rocq Tactics Still Allowed

These are allowed as low-level support tactics, especially inside `by ...` or `{ ... }` justifications, and for finishing a goal after the high-level structure is in place:

| Tactic | Purpose |
|--------|---------|
| `intros.` / `intros x y H.` | Introduce binders when the skeleton still uses standard Rocq structure |
| `rewrite lemma.` / `rewrite <- lemma.` | Equality rewriting |
| `apply lemma.` / `eapply lemma.` | Lemma application |
| `exact term.` | Exact proof term |
| `simpl.` / `cbn.` | Definitional simplification |
| `reflexivity.` | Close a reflexive equality |
| `lia.` | Linear arithmetic when `Lia` is imported |
| `nia.` | Nonlinear arithmetic |
| `ring.` | Ring equalities |
| `destruct H as [x Hx].` | Case split / unpack |
| `exists witness.` | Witness construction |
| `split.` / `left.` / `right.` | Basic logical structure |

## Do Not Use

| Tactic / pattern | Reason |
|------------------|--------|
| `assume ...` | Superseded here by `pick ...` / `intros ...` |
| `simplify lhs ... using ltac:(...)` | Old syntax; the current library uses `simplify lhs (a = b) by tac.` or `. { tac. }` |
| `simplify rhs ... using ltac:(...)` | Old syntax |
| Uppercase Angelito keywords in proof output | `ASSUME`, `FACT`, `SIMPLIFY`, `THEREFORE`, `CONCLUDE` are Angelito source syntax, not Rocq tactics |
| Extra tactics after a terminal closer like `lia.` or `exact ... .` | Usually causes `No such goal` compile failures |

## Angelito Keyword -> Rocq Mapping

| Angelito | Rocq |
|----------|------|
| `ASSUME x : T` | `pick x : T.` when using the Angelito Ltac1 layer, otherwise `intros x.` |
| `GOAL: formula` | `assert_goal (formula).` |
| `SIMPLIFY RHS expr1 = expr2 [BY ...]` | `simplify rhs (expr1 = expr2) by ... .` or `. { ... }` |
| `SIMPLIFY LHS expr1 = expr2 [BY ...]` | `simplify lhs (expr1 = expr2) by ... .` or `. { ... }` |
| `FACT h: stmt [BY lemma]` | `assert (h : stmt). { apply lemma. }` or `{ exact lemma. }` |
| `THEREFORE conclusion [BY h1]` | `exact h1.` or finish the current goal after the preceding simplification/assert steps |
| `INDUCTIVE_HYPOTHESIS ih: stmt` | Use the matching `IH...` name already present in context |
