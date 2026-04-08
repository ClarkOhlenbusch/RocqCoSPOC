Require Import Lia.
From RocqCoSPOC Require Import Angelito.
Import Angelito.Ltac1.

Theorem ex2 : forall a b : nat, a <= b -> a <= S b.
Proof.
  intros.
  apply le_S.
  exact H.
Qed.
