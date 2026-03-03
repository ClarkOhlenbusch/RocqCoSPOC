# Example 2: Inequality (lia)

Use as a few-shot example in the Gemini gem.

## Formal Statement

```coq
Theorem ex2 : forall a b : nat, a <= b -> a <= S b.
Proof.
```

## Coq-Friendly Informal Proof

By intros: assume a, b : nat and H : a <= b. We must show a <= S b. This follows from linear arithmetic: a <= b implies a <= S b.

## Chain of States (output format)

State 0:

a : nat
b : nat
H : a <= b
============================
a <= S b

State 1:

No Goals
