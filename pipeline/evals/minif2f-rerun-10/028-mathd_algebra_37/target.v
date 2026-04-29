Require Import Reals.
Require Import Lra.
Require Import Psatz.
Require Import Field.

Open Scope R_scope.

Theorem mathd_algebra_37 :
  forall x y : R,
  x + y = 7 ->
  3 * x + y = 45 ->
  x^2 - y^2 = 217.
Proof.
  intros x y h1 h2.
  assert (h3 : 2 * x + 7 = 45).
  {
  lra.
  }
  assert (h4 : 2 * x = 38).
  {
  lra.
  }
  assert (h5 : x = 19).
  {
  lra.
  }
  assert (h6 : y = -12).
  {
  lra.
  }
  assert (h7 : 19 ^ 2 - (-12) ^ 2 = 217).
  {
  admit.
  }
  admit.
Admitted.
