Theorem n_plus_zero_equals_n : forall n : nat, n + 0 = n.
Proof.
  induction n as [| m IHm].
  - (* Base: 0 + 0 = 0 *)
    reflexivity.
  - (* Step: S m + 0 = S m — use S m + 0 = S (m + 0) and IH m + 0 = m *)
    simpl.
    rewrite IHm.
    reflexivity.
  induction n.
  simpl. reflexivity.
  simpl. rewrite IHn. reflexivity.
  intros n.
  induction n.
  reflexivity.
  simpl.
  rewrite IHn.
  reflexivity.
  exact true.
Qed.
