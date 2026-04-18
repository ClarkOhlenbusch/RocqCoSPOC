From RocqCoSPOC Require Import Angelito.
Import Angelito.Ltac1.

Theorem ex1 : forall n : nat, n + 0 = n.
Proof.
  intros n.
  assert_goal (n + 0 = n).
  induction n.
  - simpl.
    reflexivity.
  - simpl.
    rewrite IHn.
    reflexivity.
Qed.
