Theorem ex1 : forall n : nat, n + 0 = n.
Proof.
  intros n.
  symmetry.
  apply plus_n_O.
Qed.
