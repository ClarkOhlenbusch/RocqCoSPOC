Require Import Reals.
Require Import Lra.
Require Import Psatz.
Require Import Field.

Open Scope R_scope.

Theorem amc12a_2011_p18:
  forall (x y : R),
  Rabs (x + y) + Rabs (x - y) = 2 ->
  x^2 - 6 * x + y^2 <= 8.
Proof.
  intros x y h_sum.
  assert (h1 : x^2 - 6 * x + y^2 = (x - 3)^2 + y^2 - 9).
  {
  field.
  }
  assert (goal1 : (x - 3)^2 + y^2 <= 17).
  {
  admit.
  }
  assert (h2 : Rabs (x + y) >= 0).
  {
  admit.
  }
  assert (h3 : Rabs (x - y) >= 0).
  {
  admit.
  }
  assert (h4 : Rabs (x + y) <= 2).
  {
  admit.
  }
  assert (h5 : Rabs (x - y) <= 2).
  {
  admit.
  }
  assert (h6 : (x + y)^2 <= 4).
  {
  admit.
  }
  assert (h7 : (x - y)^2 <= 4).
  {
  admit.
  }
  assert (h8 : (x + y)^2 + (x - y)^2 <= 8).
  {
  admit.
  }
  assert (h9 : (x + y)^2 + (x - y)^2 = 2 * x^2 + 2 * y^2).
  {
  admit.
  }
  assert (h10 : 2 * x^2 + 2 * y^2 <= 8).
  {
  admit.
  }
  assert (h11 : x^2 + y^2 <= 4).
  {
  admit.
  }
  assert (h12 : (x - 3)^2 + y^2 = x^2 + y^2 - 6 * x + 9).
  {
  admit.
  }
  assert (h13 : x^2 + y^2 - 6 * x + 9 <= 4 - 6 * x + 9).
  {
  admit.
  }
  assert (h14 : 4 - 6 * x + 9 = 13 - 6 * x).
  {
  admit.
  }
  assert (h15 : (x - 3)^2 + y^2 <= 13 - 6 * x).
  {
  admit.
  }
  assert (h16 : -1 <= x <= 1).
  {
  admit.
  }
  assert (h17 : 13 - 6 * x <= 13 - 6 * (-1)).
  {
  admit.
  }
  assert (h18 : 13 - 6 * (-1) = 19).
  {
  admit.
  }
  assert (h19 : (x - 3)^2 + y^2 <= 19).
  {
  admit.
  }
  assert (h20 : (x - 3)^2 + y^2 <= 17).
  {
  admit.
  }
  admit.
Admitted.
