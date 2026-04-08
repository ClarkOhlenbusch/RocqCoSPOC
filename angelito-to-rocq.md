# Angelito to Rocq Translation Guide

This guide is the prompt-time reference for translating Angelito proof steps into executable Rocq tactics in this repository.

The generated proof files under `coq/` should import:

```coq
From RocqCoSPOC Require Import Angelito.
Import Angelito.Ltac1.
```

Those imports expose the Ltac1 wrapper layer for the Angelito tactics library.

## Core Rule

Angelito keywords are not Rocq tactics.

The rewrite stage may emit Angelito anchors like `ASSUME`, `GOAL`, or `SIMPLIFY`, but the skeleton and fill stages must emit valid Rocq code.

## Main Mappings

| Angelito form | Rocq translation |
|---|---|
| `ASSUME x : T` | Usually `pick x : T.` (or `intros x.`). **Exception:** inside an `INDUCTION` branch, `ASSUME m : T` often only renames the predecessor variable and must not emit a new binder introduction unless that branch goal actually starts with `forall`/`->`. |
| `ASSUME x : T, y : U` | `pick x : T, y : U.` |
| `GOAL: expr` | `assert_goal (expr).` |
| `SIMPLIFY RHS a = b [BY proof]` | `simplify rhs (a = b) by proof.` or `simplify rhs (a = b). { proof. }` |
| `SIMPLIFY LHS a = b [BY proof]` | `simplify lhs (a = b) by proof.` or `simplify lhs (a = b). { proof. }` |
| `INDUCTION n` | `induction n.` |
| `APPLY theorem SPLIT INTO:` | `apply theorem.` followed by bullets or braces |
| `FACT h: stmt [BY lemma]` | `assert (h : stmt). { apply lemma. }` |
| `THEREFORE stmt [BY proof]` | Usually `assert`, `exact`, or a short tactic block that proves `stmt` |
| `CONCLUDE: ... [QED]` | Close the current goal with real Rocq tactics, then eventually `Qed.` |

## Angelito Tactics Available Here

Use these high-level tactics exactly as defined in `coq/Angelito.v`:

```coq
assert_goal (expr).
pick x : nat, y : bool.
simplify rhs (a = b) by reflexivity.
simplify rhs (a = b). { rewrite lemma1, lemma2. }
simplify lhs (a = b) by reflexivity.
simplify lhs (a = b). { rewrite lemma1, lemma2. }
```

These tactics produce structured compiler feedback on failure.

## Examples

### ASSUME

Angelito:

```angelito
ASSUME x : nat, y : bool
```

Rocq:

```coq
pick x : nat, y : bool.
```

### GOAL

Angelito:

```angelito
GOAL: 2 = 1
```

Rocq:

```coq
assert_goal (2 = 1).
```

### SIMPLIFY RHS

Angelito:

```angelito
SIMPLIFY RHS 1 = 0 + 1 [BY reflexivity]
```

Rocq:

```coq
simplify rhs (1 = 0 + 1) by reflexivity.
```

or

```coq
simplify rhs (1 = 0 + 1). { reflexivity. }
```

### SIMPLIFY LHS

Angelito:

```angelito
SIMPLIFY LHS 1 + 1 = 2 [BY reflexivity]
```

Rocq:

```coq
simplify lhs (1 + 1 = 2) by reflexivity.
```

## Fill-Stage Guidance

When filling a single slot:

1. Treat the current Rocq goal state as authoritative.
2. Use `assert_goal (...)` only when the Angelito proof names an expected intermediate goal shape.
3. Use `pick ...` only when you are actually introducing binders.
4. Keep `simplify lhs/rhs` arguments parenthesized as equalities.
5. Use ordinary Rocq tactics like `intros`, `rewrite`, `apply`, `exact`, `reflexivity`, `simpl`, `cbn`, and `lia` when they are the most direct low-level step.

## Do Not Emit

Do not use these stale forms:

```coq
assume x : T.
simplify rhs a = b using ltac:(rewrite lemma).
simplify lhs a = b using ltac:(rewrite lemma).
```

Do not output Angelito keywords directly inside the generated Rocq proof body.
