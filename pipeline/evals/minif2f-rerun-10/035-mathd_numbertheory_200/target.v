Require Import Arith.
Require Import Lia.

Theorem mathd_numbertheory_200 :
  139 mod 11 = 7.
Proof.
  vm_compute.
  reflexivity.
Qed.
