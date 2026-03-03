# Example 1: Simple equality (reflexivity)

Use this as a few-shot example in the Gemini gem to show the expected CoS format.

## Formal Statement

```coq
Theorem ex1 : forall n : nat, n + 0 = n.
Proof.
```

## Coq-Friendly Informal Proof

By induction on n. For n = 0, we have 0 + 0 = 0 by definition of plus and reflexivity. For n = S m, the IH gives m + 0 = m; then S m + 0 = S (m + 0) = S m by the IH and reflexivity.

## Chain of States (output format)

State 0:

n : nat
============================
n + 0 = n

State 1:

n : nat
============================
0 + 0 = 0

State 2:

No Goals

State 3:

n : nat
m : nat
IHm : m + 0 = m
============================
S m + 0 = S m

State 4:

n : nat
m : nat
IHm : m + 0 = m
============================
S (m + 0) = S m

State 5:

No Goals

(Note: In a real run the model may produce a slightly different sequence; this illustrates the format.)
