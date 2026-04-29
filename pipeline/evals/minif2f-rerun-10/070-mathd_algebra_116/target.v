Require Import Reals.
Require Import Lra.
Require Import Psatz.
Require Import Field.

Open Scope R_scope.

Theorem mathd_algebra_116 :
  forall (k x : R),
  x = (13 - sqrt 131) / 4 ->
  2 * x^2 - 13 * x + k = 0 ->
  k = 19/4.
Proof.
  intros k x h_eq h_zero.
  assert (h_roots_eq : forall a b c : R, a <> 0 -> b^2 - 4*a*c >= 0 -> exists r1 r2 : R, a*r1^2 + b*r1 + c = 0 /\ a*r2^2 + b*r2 + c = 0 /\ (r1 = (-b + sqrt (b^2 - 4*a*c)) / (2*a)) /\ (r2 = (-b - sqrt (b^2 - 4*a*c)) / (2*a))).
  {
  intros a b c H H0.
  exists ((-b + sqrt (b ^ 2 - 4 * a * c)) / (2 * a)).
  exists ((-b - sqrt (b ^ 2 - 4 * a * c)) / (2 * a)).
  split; [ | split; [ | split ] ].
  field_simplify.
  unfold Rdiv.
  ring_simplify.
  rewrite Rsqr_sqrt by assumption.
  field.
  assumption.
  }
  assert (h_quad : exists r1 r2 : R, 2*r1^2 - 13*r1 + k = 0 /\ 2*r2^2 - 13*r2 + k = 0 /\ (r1 = (13 + sqrt (169 - 8*k)) / 4) /\ (r2 = (13 - sqrt (169 - 8*k)) / 4)).
  {
  admit.
  }
  destruct h_quad as [r1 [r2 [h_root1 [h_root2 [h_form1 h_form2]]]]].
  assert (h_match : (13 - sqrt 131) / 4 = (13 + sqrt (169 - 8*k)) / 4 \/ (13 - sqrt 131) / 4 = (13 - sqrt (169 - 8*k)) / 4).
  {
  admit.
  }
  destruct h_match as [h_case1 | h_case2].
  - assert (h_sqrt_eq1 : sqrt (169 - 8*k) = - sqrt 131).
  {
  admit.
  }
  assert (h_nonneg : sqrt (169 - 8*k) >= 0).
  {
  admit.
  }
  assert (h_neg : - sqrt 131 < 0).
  {
  admit.
  }
  admit.
  - assert (h_sqrt_eq2 : sqrt (169 - 8*k) = sqrt 131).
  {
  admit.
  }
  assert (h_sq_eq : (sqrt (169 - 8*k))^2 = (sqrt 131)^2).
  {
  admit.
  }
  assert (h_simpl_sq : 169 - 8*k = 131).
  {
  admit.
  }
  assert (h_arith : k = 19/4).
  {
  admit.
  }
  admit.
Admitted.
