(* Formalization of: forall n, n * 0 = 0, by induction on n. *)

Theorem mul_n_0 : forall n : nat, n * 0 = 0.
Proof.
  intro n.
  induction n as [| n' IHn'].
  - (* Base case: n = 0 *)
    simpl.
    reflexivity.
  - (* Inductive case: assume n' * 0 = 0, prove (S n') * 0 = 0 *)
    simpl.
    rewrite IHn'.
    reflexivity.
Qed.
