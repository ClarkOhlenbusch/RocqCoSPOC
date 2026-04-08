From Ltac2 Require Import Ltac2.
Require Import Ltac2.Printf.
Require Import Ltac2.Notations.
Require Import Ltac2.Std.

Require Import Setoid.
Module API.

  Ltac2 Type exn ::= [ Fail_with (message) ].

  (* Fails with a message. Throws a recoverable error with zero. *)
  Ltac2 fail_with (msg:message) :=
    Control.zero (Fail_with msg).

  (* Assert that a thunk fails: if it fails, returns (), if it succeeds, fails *)
  Ltac2 assert_fails (t : unit -> unit) : unit :=
    match Control.case t with
    | Val (_exc, _cont) =>
      Control.zero (Fail_with (fprintf "assert_fail: did not throw exceptions"))
    | Err _ => ()
    end.

  Ltac2 assert_true (b:bool) : unit :=
    if b then
      ()
    else
      fail_with (fprintf "assert_true: returned false").

  Ltac2 assert_false (b:bool) : unit :=
    if b then
      fail_with (fprintf "assert_false: returned true")
    else
      ().

  (* Return true if the goal is of the given type. *)
  Ltac2 goal_is (ty : constr) : bool :=
    let goal := Control.goal () in
    Constr.equal goal ty.

  (* Matches an equality if possible *)
  Ltac2 to_eq (g: constr) : (constr * constr) option :=
    match! g with
    | ?x = ?y => Some (x, y)
    | _ => None
    end.

  (* Matches an equality if possible *)
  Ltac2 to_arrow (g: constr) : constr option :=
    match! g with
    | ?x -> _ => Some x
    | _ => None
    end.

  Ltac2 to_ident (c:constr) : ident option :=
    match Constr.Unsafe.kind c with
    | Constr.Unsafe.Var x => Some x
    | _ => None
    end.

  Ltac2 join (o:'a option option) : 'a option :=
    match o with
    | Some o => o
    | None => None
    end.

  Ltac2 unwrap (o:'a option) (m:message) :=
    match o with
    | Some a => a
    | None => fail_with m
    end.

  (* Reduces before testing for equality *)
  Ltac2 red_equal (lhs: constr) (rhs: constr) : bool :=
    let r_lhs := eval cbv in $lhs in
    let r_rhs := eval cbv in $rhs in
    Constr.equal r_lhs r_rhs.

  Ltac2 goal_to_eq () :=
    let goal := Control.goal () in
    let p := unwrap (to_eq goal)
      (fprintf "assert_rhs: Expecting an equality, but got:\n%t" goal)
    in
    p.

  Ltac2 goal_to_arrow () :=
    let goal := Control.goal () in
    let p := unwrap (to_arrow goal)
      (fprintf "Expecting goal to have a forall binder, but got:\n%t" goal)
    in
    p.

  Ltac2 assert_rhs (expected: constr) :=
    let (_, obtained) := goal_to_eq () in
    if red_equal obtained expected then
      ()
    else
      fail_with (fprintf "assert_rhs: Expected RHS:\n%t\nbut got:\n%t" expected obtained).

  Ltac2 assert_lhs (expected: constr) :=
    let (obtained, _) := goal_to_eq () in
    if red_equal obtained expected then
      ()
    else
      fail_with (fprintf "assert_lhs: Expected LHS:\n%t\nbut got:\n%t" expected obtained).

  (* Ensures that the type is the given type *)
  Ltac2 assert_goal (ty : constr) : unit :=
    let goal := Control.goal () in
    if Constr.equal goal ty then
      ()
    else
      fail_with (fprintf "Expected goal:\n%tGot:\n%t" ty goal).

  Ltac2 pick1 (x:ident) (ty:constr) :=
    let given := goal_to_arrow() in
    intros $x;
    if Constr.equal given ty then () else
    fail_with (fprintf "pick (%I:%t)\nUnexpeced type got:\n%t" x ty given).

  (* Generalize pick to a list of binders *)
  Ltac2 rec pick (l:(ident*constr) list) :=
    match l with
    | [] => ()
    | (x,ty)::l => pick1 x ty; pick l
    end.

  Ltac2 find_hyp_opt (ty:constr) : ident option := 
    match! goal with 
    | [ h : _ |- _ ] =>
      let h := Control.hyp h in
      let x := Fresh.in_goal @x in
      pose (x := $h : $ty);
      clear $x;
      to_ident h
    | [ |- _ ] => None
    end.

  (* Find a hypothesis by pattern matching, returns the first hit.
     Returns the reference of the assumption (an identifier). *)
  Ltac2 find_hyp (ty:constr) : ident :=
    unwrap (find_hyp_opt ty) (fprintf "Hypothesis not found: %t" ty).

  (* Renames a hypothesis that matches pattern [ty] into name [x]. *)
  Ltac2 rename_hyp (ty:constr) (x:ident) : unit :=
    rename [find_hyp ty, x].

  Ltac2 simplify_lhs_by (r1: constr) (r2: constr) (cont:unit -> unit) :=
    assert_lhs r1;
    let x := Fresh.in_goal @x in
    assert (x: $r1 = $r2) by cont ();
    rewrite &x at 1;
    clear $x.

  Ltac2 simplify_lhs (r1: constr) (r2: constr) :=
    assert_lhs r1;
    let x := Fresh.in_goal @x in
    assert (x: $r1 = $r2);
    Control.focus 2 2 (fun () =>
      rewrite &x at 1;
      clear $x
    ).

  Ltac2 simplify_rhs_by (r1: constr) (r2: constr) (cont:unit -> unit) :=
    assert_rhs r1;
    symmetry;
    simplify_lhs_by r1 r2 cont;
    symmetry.

  Ltac2 simplify_rhs (r1: constr) (r2: constr) :=
    assert_rhs r1;
    symmetry;
    simplify_lhs r1 r2;
    symmetry.

  (** Ltac1 FFI *)

  (* Ltac1 FFI wrapper for assert_goal *)
  Ltac ltac1_assert_goal :=
    ltac2:(ty |- Control.enter (fun _ =>
      let c := unwrap (Ltac1.to_constr ty) (fprintf "ltac1_assert_goal: conversion error") in
      assert_goal c
    )).

  (* Ltac1 FFI wrapper for simplify_lhs *)
  Ltac ltac1_simplify_lhs :=
    ltac2:(eq_constr |- Control.enter (fun _ =>
      let c_eq := unwrap (Ltac1.to_constr eq_constr) (fprintf "ltac1_simplify_lhs: conversion error") in
      let (r1, r2) := unwrap (to_eq c_eq) (fprintf "ltac1_simplify_lhs: expected equation") in
      simplify_lhs r1 r2
    )).

  (* Ltac1 FFI wrapper for simplify_rhs *)
  Ltac ltac1_simplify_rhs :=
    ltac2:(eq_constr |- Control.enter (fun _ =>
      let c_eq := unwrap (Ltac1.to_constr eq_constr) (fprintf "ltac1_simplify_rhs: conversion error") in
      let (r1, r2) := unwrap (to_eq c_eq) (fprintf "ltac1_simplify_rhs: expected equation") in
      simplify_rhs r1 r2
    )).

  (* Ltac1 FFI wrapper for simplify_rhs_by *)
  Ltac ltac1_simplify_rhs_by :=
    ltac2:(eq_constr tac |- Control.enter (fun _ =>
      let c_eq := unwrap (Ltac1.to_constr eq_constr) (fprintf "ltac1_simplify_rhs_by: conversion error") in
      let (r1, r2) := unwrap (to_eq c_eq) (fprintf "ltac1_simplify_rhs_by: expected equation") in
      let dummy := Ltac1.of_constr '1 in
      let cont := fun () => Ltac1.apply tac [dummy] Ltac1.run in
      simplify_rhs_by r1 r2 cont
    )).

  (* Ltac1 FFI wrapper for simplify_lhs_by *)
  Ltac ltac1_simplify_lhs_by :=
    ltac2:(eq_constr tac |- Control.enter (fun _ =>
      let c_eq := unwrap (Ltac1.to_constr eq_constr) (fprintf "ltac1_simplify_lhs_by: conversion error") in
      let (r1, r2) := unwrap (to_eq c_eq) (fprintf "ltac1_simplify_lhs_by: expected equation") in
      let dummy := Ltac1.of_constr '1 in
      let cont := fun () => Ltac1.apply tac [dummy] Ltac1.run in
      simplify_lhs_by r1 r2 cont
    )).

  (* Ltac1 FFI wrapper for pick1 *)
  Ltac ltac1_pick1 :=
    ltac2:(x ty |- Control.enter (fun _ =>
      let x_ident := unwrap (Ltac1.to_ident x) (fprintf "ltac1_pick1: x must be convertible to ident") in
      let ty_constr := unwrap (Ltac1.to_constr ty) (fprintf "ltac1_pick1: expected term for type") in
      pick1 x_ident ty_constr
    )).

  (** Test cases: *)

  (* Usage example: *)
  Goal False.
    assert_fails (fun () => fail_with (fprintf "fail_with")).
  Abort.

  Goal False.
    assert_true true.
    assert_fails (fun () => assert_true false).
  Abort.

  Goal False.
    assert_false false.
    assert_fails (fun () => assert_false true).
  Abort.

  (* A few test cases for using goal_is *)
  Goal False.
    assert_true (goal_is 'False).
    assert_false (goal_is 'True).
  Abort.

  Goal True.
  Proof.
    assert_goal 'True.
    assert_fails (fun () => assert_goal 'False).
  Abort.

  (* Example of using find_hyp *)
  Goal forall (P:Prop), P/\P -> P.
    intros P foo.
    let x := find_hyp '(_/\_) in
    rename [(x,@bar)].
    destruct bar.
  Abort.

  (* Example usage *)
  Goal forall (P:Prop), P/\P -> P.
    intros P foo.
    rename_hyp '(_ /\ _) @bar.
    destruct bar.
  Abort.

  Goal 1 + 1 = 1.
    (* replace 1 by 0 + 1 using reflexivity *)
    simplify_lhs_by '(1 + 1) '2 (fun () => 
      Std.reflexivity ()
    ).
    assert_goal '(2 = 1).
    simplify_lhs '2 '(1 + 1). { Std.reflexivity (). }
    assert_goal '(1 + 1 = 1).
  Abort.

  Goal 2 = 1.
    (* replace 1 by 0 + 1 using reflexivity *)
    simplify_rhs_by '1 '(0 + 1) Std.reflexivity.
    assert_goal '(2 = 0 + 1).
    simplify_rhs '(0 + 1) '1. { Std.reflexivity (). }
    assert_goal '(2 = 1).
  Abort.

  (** Ltac1 test cases: *)
  Set Default Proof Mode "Classic".

  (* Test: assert_goal *)
  Goal True.
    ltac1_assert_goal True.
  Abort.

  (* Test: simplify rhs *)
  Goal 2 = 1.
    ltac1_simplify_rhs (1 = 0 + 1). { reflexivity. }
    ltac1_assert_goal (2 = 0 + 1).
  Abort.

  (* Test: simplify lhs *)
  Goal 1 + 1 = 1.
    ltac1_simplify_lhs (1 + 1 = 2). { reflexivity. }
    ltac1_assert_goal (2 = 1).
  Abort.

  (* Test: simplify rhs by *)
  Goal 2 = 1.
    ltac1_simplify_rhs_by (1 = 0 + 1) ltac:(fun _ => reflexivity).
    ltac1_assert_goal (2 = 0 + 1).
  Abort.

  (* Test: simplify lhs by *)
  Goal 1 + 1 = 1.
    ltac1_simplify_lhs_by (1 + 1 = 2) ltac:(fun _ => reflexivity).
    ltac1_assert_goal (2 = 1).
  Abort.

End API.

Module Ltac2.
  (* Aborts execution if the current goal is not this. *)
  Ltac2 Notation "assert_goal" ty(constr) := API.assert_goal ty.

  (* Defines the pick notation, comma separated variable declaration. *)
  Ltac2 Notation "pick" l(list1(seq(ident,seq(":",constr)), ",")) := API.pick l.

  Ltac2 Notation "simplify" "rhs" r(constr) "by" x(thunk(tactic)) :=
    let (r1, r2) := API.unwrap (API.to_eq r) (fprintf "simplify rhs") in
    API.simplify_rhs_by r1 r2 x.

  Ltac2 Notation "simplify" "rhs" r(constr) :=
    let (r1, r2) := API.unwrap (API.to_eq r) (fprintf "simplify rhs") in
    API.simplify_rhs r1 r2.

  Ltac2 Notation "simplify" "lhs" r(constr) "by" x(thunk(tactic)) :=
    let (r1, r2) := API.unwrap (API.to_eq r) (fprintf "simplify lhs") in
    API.simplify_lhs_by r1 r2 x.

  Ltac2 Notation "simplify" "lhs" r(constr) :=
    let (r1, r2) := API.unwrap (API.to_eq r) (fprintf "simplify lhs") in
    API.simplify_lhs r1 r2.

  (** Test cases *)

  (* Example of using assert goal *)
  Goal forall (x:nat), x <> 0 -> exists n, S n = x.
  Proof.
    intros.
    assert_goal (exists n, S n = x).
    API.assert_fails (fun () => assert_goal False). (* Fails when given an unexpected type *)
  Abort.

  (* Example usage of pick: *)
  Goal forall (x:nat) (y : bool), if y then x = 1 else x = 0.
    pick x : nat, y: bool.
    (* test that we have indeed introduced the 2 binders *)
    assert_goal (if y then x = 1 else x = 0).
  Abort.

  Goal 1 + 1 = 1.
    simplify rhs (1 = 0 + 1) by reflexivity ().
    assert_goal (1 + 1 = 0 + 1).
  Abort.

  Goal 1 + 1 = 1.
    simplify rhs (1 = 0 + 1). { reflexivity (). }
    assert_goal (1 + 1 = 0 + 1).
  Abort.

  Goal 1 + 1 = 1.
    simplify lhs (1 + 1 = 2) by reflexivity ().
    assert_goal (2 = 1).
  Abort.

  Goal 1 + 1 = 1.
    simplify lhs (1 + 1 = 2). { reflexivity (). }
    assert_goal (2 = 1).
  Abort.
End Ltac2.

Module Ltac1.
  Set Default Proof Mode "Classic".

  (* Ltac1 Notations (top-level) *)
  Tactic Notation "assert_goal" constr(ty) :=
    API.ltac1_assert_goal ty.

  Tactic Notation "simplify" "rhs" constr(eq) :=
    API.ltac1_simplify_rhs eq.

  Tactic Notation "simplify" "lhs" constr(eq) :=
    API.ltac1_simplify_lhs eq.

  Tactic Notation "simplify" "rhs" constr(eq) "by" tactic(tac) :=
    API.ltac1_simplify_rhs_by eq ltac:(fun _ => tac).

  Tactic Notation "simplify" "lhs" constr(eq) "by" tactic(tac) :=
    API.ltac1_simplify_lhs_by eq ltac:(fun _ => tac).

  (* pick notations - 1 argument *)
  Tactic Notation "pick" ident(x) ":" constr(ty) :=
    API.ltac1_pick1 x ty.

  (* pick notations - 2 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2.

  (* pick notations - 3 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3.

  (* pick notations - 4 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) "," ident(x4) ":" constr(ty4) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3;
    API.ltac1_pick1 x4 ty4.

  (* pick notations - 5 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) "," ident(x4) ":" constr(ty4) ","
                ident(x5) ":" constr(ty5) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3;
    API.ltac1_pick1 x4 ty4; API.ltac1_pick1 x5 ty5.

  (* pick notations - 6 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) "," ident(x4) ":" constr(ty4) ","
                ident(x5) ":" constr(ty5) "," ident(x6) ":" constr(ty6) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3;
    API.ltac1_pick1 x4 ty4; API.ltac1_pick1 x5 ty5; API.ltac1_pick1 x6 ty6.

  (* pick notations - 7 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) "," ident(x4) ":" constr(ty4) ","
                ident(x5) ":" constr(ty5) "," ident(x6) ":" constr(ty6) ","
                ident(x7) ":" constr(ty7) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3;
    API.ltac1_pick1 x4 ty4; API.ltac1_pick1 x5 ty5; API.ltac1_pick1 x6 ty6;
    API.ltac1_pick1 x7 ty7.

  (* pick notations - 8 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) "," ident(x4) ":" constr(ty4) ","
                ident(x5) ":" constr(ty5) "," ident(x6) ":" constr(ty6) ","
                ident(x7) ":" constr(ty7) "," ident(x8) ":" constr(ty8) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3;
    API.ltac1_pick1 x4 ty4; API.ltac1_pick1 x5 ty5; API.ltac1_pick1 x6 ty6;
    API.ltac1_pick1 x7 ty7; API.ltac1_pick1 x8 ty8.

  (* pick notations - 9 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) "," ident(x4) ":" constr(ty4) ","
                ident(x5) ":" constr(ty5) "," ident(x6) ":" constr(ty6) ","
                ident(x7) ":" constr(ty7) "," ident(x8) ":" constr(ty8) ","
                ident(x9) ":" constr(ty9) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3;
    API.ltac1_pick1 x4 ty4; API.ltac1_pick1 x5 ty5; API.ltac1_pick1 x6 ty6;
    API.ltac1_pick1 x7 ty7; API.ltac1_pick1 x8 ty8; API.ltac1_pick1 x9 ty9.

  (* pick notations - 10 arguments *)
  Tactic Notation "pick" ident(x1) ":" constr(ty1) "," ident(x2) ":" constr(ty2) ","
                ident(x3) ":" constr(ty3) "," ident(x4) ":" constr(ty4) ","
                ident(x5) ":" constr(ty5) "," ident(x6) ":" constr(ty6) ","
                ident(x7) ":" constr(ty7) "," ident(x8) ":" constr(ty8) ","
                ident(x9) ":" constr(ty9) "," ident(x10) ":" constr(ty10) :=
    API.ltac1_pick1 x1 ty1; API.ltac1_pick1 x2 ty2; API.ltac1_pick1 x3 ty3;
    API.ltac1_pick1 x4 ty4; API.ltac1_pick1 x5 ty5; API.ltac1_pick1 x6 ty6;
    API.ltac1_pick1 x7 ty7; API.ltac1_pick1 x8 ty8; API.ltac1_pick1 x9 ty9;
    API.ltac1_pick1 x10 ty10.

  (* Test cases *)

  Goal False.
    assert_goal False.
  Abort.

  Goal 1 + 1 = 1.
    simplify rhs (1 = 0 + 1). { reflexivity. }
    assert_goal (1 + 1 = 0 + 1).
  Abort.

  Goal 1 + 1 = 1.
    simplify lhs (1 + 1 = 2). { reflexivity. }
    assert_goal (2 = 1).
  Abort.

  Goal 2 = 1.
    simplify rhs (1 = 0 + 1) by reflexivity.
    assert_goal (2 = 0 + 1).
  Abort.

  Goal 1 + 1 = 1.
    simplify lhs (1 + 1 = 2) by reflexivity.
    assert_goal (2 = 1).
  Abort.

  (* Test: pick - 1 argument *)
  Goal forall (x:nat), x = 1.
    pick x : nat.
    assert_goal (x = 1).
  Abort.

  (* Test: pick - 2 arguments *)
  Goal forall (x:nat) (y : bool), if y then x = 1 else x = 0.
    pick x : nat, y : bool.
    assert_goal (if y then x = 1 else x = 0).
  Abort.

  (* Test: pick - 5 arguments *)
  Goal forall (a:nat) (b:bool) (c:nat) (d:bool) (e:nat), a + c = e.
    pick a : nat, b : bool, c : nat, d : bool, e : nat.
    assert_goal (a + c = e).
  Abort.

  (* Test: pick - 10 arguments *)
  Goal forall (x1:nat) (x2:nat) (x3:nat) (x4:nat) (x5:nat) (x6:nat) (x7:nat) (x8:nat) (x9:nat) (x10:nat),
    x1 + x2 = x3.
    pick x1 : nat, x2 : nat, x3 : nat, x4 : nat, x5 : nat, x6 : nat, x7 : nat, x8 : nat, x9 : nat, x10 : nat.
    assert_goal (x1 + x2 = x3).
  Abort.

End Ltac1.
