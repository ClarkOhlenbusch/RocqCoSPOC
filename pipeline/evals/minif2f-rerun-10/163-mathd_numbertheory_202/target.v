Require Import Coq.Arith.PeanoNat.

Theorem mathd_numbertheory_202 :
  (19^19 + 99^99) mod 10 = 8.
Proof.
  assert ((19 ^ 19 + 99 ^ 99) mod 10 = (9 ^ 19 + 9 ^ 99) mod 10).
  {
  admit.
  }
  assert (forall k, (9 ^ (2 * k)) mod 10 = 1 /\ (9 ^ (2 * k + 1)) mod 10 = 9).
  {
  admit.
  }
  assert (h19 : (9 ^ 19) mod 10 = 9).
  {
  admit.
  }
  assert (h99 : (9 ^ 99) mod 10 = 9).
  {
  admit.
  }
  assert ((9 ^ 19 + 9 ^ 99) mod 10 = (9 + 9) mod 10).
  {
  admit.
  }
  assert ((9 + 9) mod 10 = 18 mod 10).
  {
  admit.
  }
  assert (18 mod 10 = 8).
  {
  admit.
  }
  admit.
Admitted.
