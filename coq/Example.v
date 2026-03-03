(* Example from data/few_shot/example01_simple_eq.md — use CoS workflow to fill tactics. *)

Theorem ex1 : forall n : nat, n + 0 = n.
Proof.
  (* Chain of states: State 0 (n + 0 = n) -> ... -> No Goals.
     Add tactics here; VsRocq/VsCoq will check. *)
  intro n.
  induction n as [| m IHm].
  - reflexivity.
  - simpl.
    rewrite IHm.
    reflexivity.
Qed.
