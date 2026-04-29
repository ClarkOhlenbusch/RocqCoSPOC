Require Import Reals.
Require Import Lra.
Require Import Psatz.
Require Import Field.

Open Scope R_scope.

Theorem amc12a_2017_p2:
  forall (x y : R),
  x <> 0 ->
  y <> 0 ->
  x + y = 4 * (x * y) ->
  (1 / x) + (1 / y) = 4.
Proof.
  intros x y hx hy hsum.
  assert (h1 : (1 / x) + (1 / y) = (x + y) / (x * y)).
  {
  admit.
  }
  assert (h2 : (x + y) / (x * y) = (4 * (x * y)) / (x * y)).
  {
  admit.
  }
  assert (h3 : (4 * (x * y)) / (x * y) = 4).
  {
  admit.
  }
  admit.
Admitted.
