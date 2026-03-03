(* Congruence implies equality under bounds and coprimality.
   Formalization of the proof chain:
   State 0: Hmod (j+a*E mod w = j+b*E mod w) -> a = b
   State 1: convert to divisibility w | (j+a*E)-(j+b*E)
   State 2: simplify to w | (a-b)*E
   State 3: Gauss: w | a-b
   State 4: unfold divide to a - b = t*w
   State 5: bounds + lia -> t=0 -> a=b
*)

Require Import ZArith.
Require Import Znumtheory.
Require Import Lia.

Definition is_complete_residue_system (w : Z) (f : Z -> Z) : Prop :=
  forall a b : Z,
    0 <= a < w ->
    0 <= b < w ->
    f a mod w = f b mod w ->
    a = b.

Theorem cong_mod_implies_eq :
  forall j w E a b : Z,
    Z.gcd w E = 1 ->
    0 <= a < w ->
    0 <= b < w ->
    (j + a * E) mod w = (j + b * E) mod w ->
    a = b.
Proof.
  intros j w E a b Hgcd Ha Hb Hmod.
  (* State 1: mod equality -> w divides the difference *)
  assert (Hw : w <> 0) by lia.
  assert (Hmod_eq_zero : ((j + a * E) - (j + b * E)) mod w = 0).
  {
    rewrite Zminus_mod, Hmod, Z.sub_diag.
    apply Z.mod_0_l.
    exact Hw.
  }
  assert (Hdiv1 : (w | (j + a * E) - (j + b * E))).
  {
    apply Zmod_divide.
    - exact Hw.
    - exact Hmod_eq_zero.
  }
  (* State 2: simplify (j + a*E) - (j + b*E) = (a - b) * E *)
  assert (Hdiv2 : (w | (a - b) * E)).
  {
    replace ((a - b) * E) with ((j + a * E) - (j + b * E)) by ring.
    exact Hdiv1.
  }
  (* State 3: Gauss: gcd w E = 1 and w | (a-b)*E => w | a-b *)
  assert (Hrel : rel_prime w E).
  {
    exact (proj1 (Zgcd_1_rel_prime w E) Hgcd).
  }
  rewrite Z.mul_comm in Hdiv2.
  apply Gauss with (a := w) (b := E) (c := a - b) in Hdiv2; auto.
  (* State 4: w | a - b => exists t, a - b = t * w *)
  destruct Hdiv2 as [t Ht].
  (* State 5: bounds: -w < a-b < w and a-b = t*w => t=0 => a=b *)
  assert (Hbound : -w < t * w < w) by (rewrite <- Ht; lia).
  destruct (Z.eq_dec t 0) as [Ht0|Ht0].
  - (* t = 0: then a - b = 0 * w = 0, so a = b *)
    rewrite Ht0, Z.mul_0_l in Ht.
    lia.
  - (* t <> 0 and w > 0 => |t*w| >= w, contradiction with Hbound *)
    assert (Hw_pos : 0 < w) by lia.
    nia.
Qed.

Theorem complete_residue_system_add_mul :
  forall j w E : Z,
    Z.gcd w E = 1 ->
    is_complete_residue_system w (fun k => j + k * E).
Proof.
  intros j w E H_gcd a b Ha Hb Hmod.
  exact (cong_mod_implies_eq j w E a b H_gcd Ha Hb Hmod).
Qed.
