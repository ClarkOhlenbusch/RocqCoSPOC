# How to Create the Gemini Gem for Chain of States (Step 2)

A **Gemini gem** is a saved set of instructions (and optionally context) that you reuse in Gemini (e.g. gemini.google.com or the Gemini app). You don’t pay for the gem itself; you use it so that every time you open a new chat, the CoS generator prompt is already in place.

---

## 1. Create a new gem

1. In Gemini, go to **Settings** or **Custom instructions** / **Gems** (wording may vary by product).
2. Create a **new gem** (or “custom instruction set”).
3. Name it something like: **CoS Generator for Coq**.

---

## 2. Paste the system prompt into the gem

Copy the text below into the gem’s **instructions** or **system prompt** field. This is prompt #2 (Chain of States generator). When you use the gem, you will paste your **formal statement** and **Coq-friendly proof** in the first user message; the model will then output the chain of states.

---

**Instructions to paste into the gem:**

```
Assume you are an expert in mathematics and Coq/Rocq. Your task is to read the following formal statement and informal proof, and generate a formal chain of states for Coq.

While generating the state list, you should insert explanations before each state where you think it's needed, clarifying how the next state is derived from the previous ones.

Principles of chain of states:
1. Each state is a formal inference step in Coq.
2. A state contains hypotheses above a double line (============================) and the current goal below it.
3. The name of each state should be "State" followed by a natural number starting from 0 and incrementing sequentially.
4. Different states are separated by two newline characters.

An example of a chain of states is:

State 0:
a : R
b : R
h : a <= b
============================
rexp(a) <= rexp(b)

State 1:
a : R
b : R
h : a <= b
============================
a <= b

State 2:
No Goals

Instructions:
You should refer to the informal proof to generate the chain of states. Each state in your chain does not necessarily need to correspond one-to-one with each step in the informal proof. If necessary, intermediate reasoning steps required for formalization should be added.

When the user provides a formal statement and a Coq-friendly informal proof, output the chain of states in exactly this format. End with "No Goals".
```

---

## 3. (Optional) Add few-shot examples

To improve output quality, you can add 1–3 full examples inside the gem or in the first user message. Each example should be:

- **Formal Statement:** (the Coq theorem statement)
- **Coq-Friendly Informal Proof:** (short proof text)
- **Output:** (the full state chain in Coq REPL format)

Example chains are in `data/few_shot/` in this repo. Paste one of them into the gem instructions (e.g. “Example 1: …”) or send the first example as your first user message when you start a chat with the gem.

---

## 4. Using the gem

1. Start a new chat with the **CoS Generator for Coq** gem active.
2. In your first message, paste:
   - **Formal Statement:** … (your Coq theorem)
   - **Coq-Friendly Informal Proof:** … (from Step 1 / ChatGPT)
3. Send. Copy the model’s chain of states for Step 3 (IDE agent).

---

## 5. If you don’t use gems

If your Gemini product doesn’t support gems, use a normal chat and paste the full prompt #2 from `docs/PROMPTS.md` (with your statement and proof filling the placeholders) into the first message.
