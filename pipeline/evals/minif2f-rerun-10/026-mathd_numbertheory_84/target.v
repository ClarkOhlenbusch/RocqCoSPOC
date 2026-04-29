Require Import Reals.
Require Import Coquelicot.Coquelicot.
Require Import Lra.
Require Import Psatz.
Require Import Field.

Open Scope R_scope.

Theorem mathd_numbertheory_84 :
  floor ((9 / 160) * 100) = 5%Z.
Proof.
  assert (H : (9 / 160) * 100 = 45 / 8).
  {
  field_simplify.
  lra.
  }
  assert (h1 : 45 / 8 = 5 + 5/8).
  {
  field_simplify.
  lra.
  }
  assert (h2 : 5 <= 45/8 < 6).
  {
  lra.
  }
  admit.
Admitted.
