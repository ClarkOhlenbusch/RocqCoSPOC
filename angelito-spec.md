# Angelito Language Specification

Angelito is a pseudo-proof language designed to describe formal mathematical proofs in a readable, structured way. It bridges the gap between mathematical intuition and formal proof code.

## Grammar Structure

```
PROOF ::= PROVE <theorem_name> ":" <signature> <body>

SIGNATURE ::= "∀" <vars> "." <formula>
            | <formula>

BODY ::= BEGIN <statements> END

STATEMENTS ::= <statement>
             | <statement> <statements>

STATEMENT ::= <intro_stmt>
            | <simplify_stmt>
            | <goal_stmt>
            | <apply_stmt>
            | <induction_stmt>
            | <prove_stmt>
            | <reasoning_stmt>
            | <conclude_stmt>
```

## Keywords Reference

### Structural Keywords

#### **PROVE**
- **Scope**: Top-level, can be nested
- **Purpose**: Declares the start of a proof block
- **Usage**: `PROVE <theorem_name>: <signature>`
- **Example**: `PROVE max_pointwise_sub_rw: ∀n. max(...) = max(...) - max(...)`
- **Semantics**: Introduces a new proof obligation or sub-proof. Opens a proof context.

#### **BEGIN / END**
- **Scope**: Paired delimiters
- **Purpose**: Delimits the proof body
- **Usage**: `BEGIN <proof_body> END`
- **Semantics**: Marks the start and end of a proof's logical content. All statements between BEGIN and END are part of this proof.

### Introduction and Binding Keywords

#### **ASSUME**
- **Scope**: Early in proof, after BEGIN
- **Purpose**: Introduces assumptions, parameters, or universally quantified variables into the proof context
- **Usage**: `ASSUME <var> : <type>` or `ASSUME <var> : <type>, <var> : <type>, ...`
- **Example**: `ASSUME n : ℕ`
- **Semantics**: Binds variables with their types and makes them available for use in subsequent proof steps.

### Transformation Keywords

#### **SIMPLIFY**
- **Scope**: After ASSUME, before main proof
- **Purpose**: Shows algebraic or computational simplification of expressions
- **Usage**:
  ```
  SIMPLIFY <side> :
    <expr1>
    = <expr2>    [BY <justification>]
  ```
- **Example**:
  ```
  SIMPLIFY RHS:
    max(seq(0)) - max(make(n))
    = Dim.prec - n    [BY max_seq_rw, max_make_rw]
  ```
- **Semantics**: Transforms an expression step-by-step, each equality justified by lemmas or rewrite rules.

### Goal and Decomposition Keywords

#### **GOAL**
- **Scope**: After simplifications
- **Purpose**: States the proof objective after all simplifications
- **Usage**: `GOAL: <formula>`
- **Example**: `GOAL: max(pointwise_sub(seq(0), make(n))) = Dim.prec - n`
- **Semantics**: Clarifies what remains to be proven after preliminary simplifications.

#### **APPLY**
- **Scope**: When decomposing a goal
- **Purpose**: Applies a theorem, lemma, or tactic to transform the proof goal
- **Usage**: `APPLY <theorem_name> SPLIT INTO: <subgoal_list>`
- **Example**: `APPLY max_iff SPLIT INTO: (1) MEMBERSHIP: ... (2) UPPER_BOUND: ...`
- **Semantics**: Reduces a complex goal into simpler subgoals using a logical rule or theorem.

#### **SPLIT INTO**
- **Scope**: Follows APPLY
- **Purpose**: Lists the resulting subgoals after applying a theorem
- **Usage**:
  ```
  APPLY <theorem> SPLIT INTO:
    (1) <subgoal_name>: <formula>
    (2) <subgoal_name>: <formula>
  ```
- **Semantics**: Enumerates the proof obligations created by the APPLY statement.

### Proof Section Keywords

#### **PROVE** (nested, for subgoals)
- **Scope**: After SPLIT INTO, for each subgoal
- **Purpose**: Focuses on proving a specific subgoal
- **Usage**: `PROVE <subgoal_name>: <optional description>`
- **Example**: `PROVE MEMBERSHIP:`
- **Semantics**: Shifts focus to one subgoal. Everything following belongs to this subgoal's proof until the next subgoal or CONCLUDE.

#### **INDUCTION**
- **Scope**: After ASSUME, to structure recursive or inductive reasoning
- **Purpose**: Declares that the proof proceeds by structural induction on a parameter or type
- **Usage**: `INDUCTION <var>`
- **Example**: `INDUCTION n`
- **Semantics**: Divides the proof into cases based on the structure of the induction parameter. Typically followed by PROVE blocks for BASE_CASE, INDUCTIVE_CASE, and similar case names. Within an INDUCTIVE_CASE, an INDUCTIVE_HYPOTHESIS can be introduced to reference the assumed property for structurally smaller values.

### Reasoning Keywords

#### **FACT**
- **Scope**: Within proof reasoning blocks
- **Purpose**: Records an intermediate fact or lemma application that contributes to the proof
- **Usage**: `FACT <name>: <statement> [BY <lemma> <args>]`
- **Example**: `FACT h1: seq(0)[Dim.prec] = Dim.prec [BY maps_to_seq]`
- **Semantics**: Establishes a named fact with explicit justification. Facts can be referenced in subsequent steps via their names (passed as arguments to BY). Used to build dependency chains showing how lemmas compose.

#### **WITNESS_AT**
- **Scope**: Within membership or existence proofs
- **Purpose**: Provides a witness (typically an index) to prove a membership or existence goal constructively
- **Usage**: `WITNESS_AT <index>:` followed by FACT statements building up to a THEREFORE conclusion
- **Example**: `WITNESS_AT Dim.prec:`
- **Semantics**: Focuses reasoning on a specific location, establishing facts at that position. Used with FACT to construct evidence (via `Vector.MapsTo`) that something exists at a particular index, culminating in a membership proof via THEREFORE.

#### **FOR_ALL**
- **Scope**: When reasoning universally
- **Purpose**: Introduces universal quantification or case-by-case reasoning
- **Usage**: `FOR_ALL <var> ∈ <set>: <statements>`
- **Example**: `FOR_ALL x ∈ pointwise_sub(seq(0), make(n)):`
- **Semantics**: States that the following reasoning applies to every element in a set.

#### **EXTRACT**
- **Scope**: When destructuring compound values
- **Purpose**: Breaks down a complex structure into its components
- **Usage**: `EXTRACT <components> FROM <structure>:`
- **Example**: `EXTRACT source elements at position i:`
- **Semantics**: Decomposes a term and binds its parts for use in subsequent reasoning.

#### **SINCE**
- **Scope**: To introduce additional constraints or facts
- **Purpose**: States a constraint, lemma, or fact that enables the next reasoning step
- **Usage**: `SINCE <condition>: <statements>`
- **Example**: `SINCE i < Dim.size: ...`
- **Semantics**: Provides a fact that justifies the reasoning that follows.

#### **INDUCTIVE_HYPOTHESIS**
- **Scope**: Within an INDUCTIVE_CASE proof block
- **Purpose**: Names and introduces the inductive hypothesis for use in the inductive case
- **Usage**: `INDUCTIVE_HYPOTHESIS <name>: <statement>` or `ASSUME <name>: <statement>`
- **Example**: `INDUCTIVE_HYPOTHESIS ih: ∀l'. length l' = n' → length (map f l') = n'`
- **Semantics**: Binds a name to the inductive hypothesis, which states the property holds for structurally smaller values. This can be applied or reasoned about just like other facts or assumptions.

### Conclusion Keywords

#### **THEREFORE**
- **Scope**: After a reasoning chain
- **Purpose**: Marks an intermediate conclusion or the result of a logical deduction
- **Usage**: `THEREFORE <statement>` or `THEREFORE <var> = <expr>`
- **Example**: `THEREFORE (Dim.prec - n) ∈ result` or `THEREFORE x = i - n`
- **Semantics**: Concludes from the immediately preceding reasoning chain. Used to transition between reasoning steps or mark the output of a sub-reasoning block. **Can appear multiple times in a proof.**

#### **CONCLUDE**
- **Scope**: At the end of the entire proof
- **Purpose**: States the final conclusion, closing all open goals
- **Usage**: `CONCLUDE: <statement>`
- **Example**: `CONCLUDE: Both conditions hold, so max = Dim.prec - n    [QED]`
- **Semantics**: Terminates the proof. Appears exactly once per PROVE block. All subgoals must be closed before CONCLUDE.

### Justification Keywords

#### **BY**
- **Scope**: After any statement requiring justification
- **Purpose**: Provides the lemma, theorem, or rule that justifies a step
- **Usage**: `<statement> [BY <lemma_name> <arg1> <arg2> ...]` or `<statement> [BY <lemma1>, <lemma2>, ...]`
- **Example**: `FACT h3: ... [BY maps_to_pointwise h1 h2]` or `= Dim.prec - n [BY max_seq_rw, max_make_rw]`
- **Semantics**: Justifies why the preceding statement is valid. Can cite multiple lemmas. Arguments (including previously-named facts) are passed to lemmas to show proof dependencies and composition. Comma-separated lemmas are applied sequentially; space-separated items are arguments to a single lemma.

## Key Distinctions

### THEREFORE vs CONCLUDE

| Aspect | THEREFORE | CONCLUDE |
|--------|-----------|----------|
| **Frequency** | Can appear multiple times | Exactly once per proof |
| **Scope** | Intermediate conclusion | Final conclusion |
| **Purpose** | Result of a reasoning chain | Closes the entire proof |
| **Context** | Within proof sections or reasoning blocks | At the very end |
| **Semantics** | "So we have..." | "Therefore, the theorem is proven" |

### APPLY vs PROVE

| Aspect | APPLY | PROVE (nested) |
|--------|-------|---|
| **Goal** | Applies a theorem to decompose | Focuses on proving a specific subgoal |
| **Used for** | Logical reduction | Proof construction |
| **Followed by** | SPLIT INTO | Reasoning statements |

### SIMPLIFY vs GOAL

| Aspect | SIMPLIFY | GOAL |
|--------|----------|------|
| **Purpose** | Shows transformation of expressions | States proof obligation after simplification |
| **Algebraic** | Yes, step-by-step | No, just the target formula |
| **Justification** | Requires [BY ...] | No justification needed |

### FACT vs THEREFORE

| Aspect | FACT | THEREFORE |
|--------|------|-----------|
| **Purpose** | Record intermediate fact for future use | Mark conclusion of a reasoning block |
| **Naming** | Always given a name (h1, h2, etc.) | No explicit name |
| **Reuse** | Referenced in later [BY ...] clauses | No forward reference |
| **Dependency** | Can depend on other facts | Depends on preceding facts implicitly |
| **Frequency** | Can appear many times | One per major reasoning block |
| **Example** | `FACT h1: expr1 = expr2 [BY lemma]` | `THEREFORE conclusion [BY h1, h2]` |

### WITNESS_AT vs FOR_ALL

| Aspect | WITNESS_AT | FOR_ALL |
|--------|-----------|---------|
| **Purpose** | Prove membership/existence constructively | Prove universal property |
| **Approach** | Provide specific witness (index) | Quantify over all elements |
| **Scope** | Fixed location | Variable ranging over set |
| **Usage** | Building FACTs at one position | Generic reasoning about arbitrary elements |
| **Ending** | THEREFORE with membership conclusion | THEREFORE with property about any element |

## Semantic Levels

1. **Structural Level**: PROVE, BEGIN, END, SPLIT INTO, INDUCTION
2. **Context Level**: ASSUME, PROVE (nested), WITNESS_AT, FOR_ALL, INDUCTIVE_HYPOTHESIS
3. **Fact Level**: FACT (records intermediate facts with dependencies), EXTRACT, SINCE
4. **Reasoning Level**: THEREFORE (intermediate), CONCLUDE (final)
5. **Justification Level**: BY (explains any step, can reference other facts)

## Example Analysis: Proof with Fact Dependencies

Here's a complete example showing how FACT and WITNESS_AT work together with proof dependencies:

```angelito
PROVE max_pointwise_sub_rw: ∀n. max(pointwise_sub(seq(0), make(n))) = max(seq(0)) - max(make(n))
  ↑ Opens proof context

BEGIN
  ASSUME n : ℕ
    ↑ Introduces parameter

  SIMPLIFY RHS: max(seq(0)) - max(make(n)) = Dim.prec - n [BY max_seq_rw, max_make_rw]
    ↑ Preprocessing through algebraic manipulation

  GOAL: max(pointwise_sub(seq(0), make(n))) = Dim.prec - n
    ↑ States what remains after simplification

  APPLY max_iff SPLIT INTO:
    (1) MEMBERSHIP: element exists
    (2) UPPER_BOUND: all elements bounded
    ↑ Decomposes main goal into subgoals

  PROVE MEMBERSHIP:
    ↑ Focus on membership subgoal

    WITNESS_AT Dim.prec:
      ↑ Provide index as witness; subsequent facts build evidence at this position

      FACT h1: seq(0)[Dim.prec] = Dim.prec [BY maps_to_seq]
        ↑ Record first component

      FACT h2: make(n)[Dim.prec] = n [BY maps_to_make]
        ↑ Record second component (independent)

      FACT h3: pointwise_sub(seq(0), make(n))[Dim.prec] = Dim.prec - n [BY maps_to_pointwise h1 h2]
        ↑ Combine using h1 and h2 (shows dependency chain)

      THEREFORE (Dim.prec - n) ∈ result [BY maps_to_to_in h3]
        ↑ Final conclusion: convert MapsTo evidence to membership proof

  PROVE UPPER_BOUND:
    ↑ Focus on upper bound subgoal

    FOR_ALL x ∈ pointwise_sub(seq(0), make(n)):
      ↑ Universal quantification over elements

      FACT h_elem : ∃i. x = seq(0)[i] - make(n)[i] [BY definition_of_pointwise]
        ↑ Decompose pointwise operation into components

      THEREFORE x ≤ Dim.prec - n [BY arithmetic_properties]
        ↑ Conclude element bound

  CONCLUDE: Both subgoals proven, so theorem holds [QED]
    ↑ All goals closed, proof complete

END
```

**Key observations:**
- **FACT naming**: Each intermediate fact gets a descriptive name (h1, h2, h3)
- **Dependency passing**: Later facts reference earlier ones: `[BY maps_to_pointwise h1 h2]`
- **Proof composition**: The [BY ...] clause shows exactly which facts feed into each lemma
- **WITNESS_AT + FACT**: Used together for constructive proofs showing existence at a specific location
- **THEREFORE placement**: Appears once per major reasoning block, marking the conclusion

## Example Analysis: Proof by Structural Induction

Here's a complete example showing how INDUCTION, BASE_CASE, INDUCTIVE_CASE, and INDUCTIVE_HYPOTHESIS work together:

```angelito
PROVE list_map_preserves_length: ∀A B (f: A → B) n l. length l = n → length (map f l) = n
  ↑ States the property: mapping a function over a list preserves its length

BEGIN
  ASSUME A : Type
  ASSUME B : Type
  ASSUME f : A → B
  ASSUME n : ℕ
  ASSUME l : list A
  ASSUME eq : length l = n
    ↑ Introduce all parameters and assumptions

  GOAL: length (map f l) = n
    ↑ State the goal to be proven

  INDUCTION n
    ↑ Perform structural induction on n, dividing into base and inductive cases

  PROVE BASE_CASE: n = 0
    ↑ Focus on base case: when n equals 0

    SINCE length l = 0:
      l = []  [BY empty_list_characterization]
        ↑ A list with length 0 must be empty

    SIMPLIFY:
      length (map f [])
      = length []      [BY map_empty]
      = 0              [BY length_empty]
        ↑ Empty list remains empty after mapping

    THEREFORE length (map f l) = 0
      ↑ Conclude the base case

    CONCLUDE: Empty lists remain empty after mapping [QED]

  PROVE INDUCTIVE_CASE: n = S n'
    ↑ Focus on inductive case: when n is the successor of n'

    ASSUME n' : ℕ
    INDUCTIVE_HYPOTHESIS ih: ∀l'. length l' = n' → length (map f l') = n'
      ↑ Introduce the inductive hypothesis for the smaller case (n')

    SINCE length l = S n':
      ∃head tail. l = head :: tail ∧ length tail = n'  [BY nonempty_list_characterization]
        ↑ A list with length S n' must have a head and tail of length n'

    ASSUME head : A
    ASSUME tail : list A
    ASSUME h_struct: l = head :: tail
    ASSUME h_tail_len: length tail = n'
      ↑ Bind the components

    SIMPLIFY:
      length (map f (head :: tail))
      = length (f head :: map f tail)  [BY map_cons]
      = 1 + length (map f tail)        [BY length_cons]
        ↑ Unfold definitions and simplify

    APPLY INDUCTIVE_HYPOTHESIS ih:
      FACT h_mapped_tail: length (map f tail) = n'  [BY ih tail h_tail_len]
        ↑ Apply the inductive hypothesis to the tail

    SIMPLIFY:
      1 + length (map f tail)
      = 1 + n'     [BY h_mapped_tail]
      = S n'       [BY successor_definition]
        ↑ Substitute and simplify to get the result

    THEREFORE length (map f l) = S n'
      ↑ Conclude the inductive case

    CONCLUDE: Non-empty lists preserve length through mapping [QED]

  CONCLUDE: By induction on list length, mapping preserves length for all n [QED]
    ↑ All cases complete; theorem proven

END
```

**Key observations for induction proofs:**
- **INDUCTION declaration**: Specifies which parameter the induction is over
- **Case-by-case proofs**: Each PROVE block handles one case (BASE_CASE, INDUCTIVE_CASE)
- **Inductive hypothesis naming**: The INDUCTIVE_HYPOTHESIS is given a name (ih) for easy reference
- **Application of hypothesis**: In the inductive case, the hypothesis is applied to structurally smaller arguments (the tail in this example)
- **Case coverage**: All structural cases of the induction parameter are addressed
- **Final CONCLUDE**: References induction to justify the universal claim

## Proof Verification Checklist for AI

When an AI reads an Angelito proof, it should verify:

1. ✓ **Binding**: All variables introduced via ASSUME before use
2. ✓ **Goal Decomposition**: All subgoals from SPLIT INTO have corresponding PROVE blocks
3. ✓ **Justifications**: Every transformation has [BY ...] justification
4. ✓ **Fact Dependencies**: Referenced facts (in [BY lemma fact1 fact2]) are defined before use
5. ✓ **WITNESS_AT Structure**: WITNESS_AT blocks contain FACTs building toward a THEREFORE conclusion
6. ✓ **Conclusion Structure**: Exactly one CONCLUDE per PROVE block
7. ✓ **Closure**: CONCLUDE states what all subgoals together prove
8. ✓ **Logical Flow**: THEREFORE steps follow from preceding reasoning blocks (WITNESS_AT, FOR_ALL, etc.)
9. ✓ **Variable Scope**: Variables extracted in EXTRACT are used before scope ends
10. ✓ **Proof Dependencies**: FACT references show which lemmas compose with which evidence
11. ✓ **Induction Structure**: INDUCTION statements have corresponding PROVE blocks for each case (BASE_CASE, INDUCTIVE_CASE, etc.)
12. ✓ **Inductive Hypothesis**: INDUCTIVE_HYPOTHESIS is introduced in inductive cases and applied appropriately to structurally smaller arguments
13. ✓ **Case Completeness**: All possible cases from the induction parameter are addressed
