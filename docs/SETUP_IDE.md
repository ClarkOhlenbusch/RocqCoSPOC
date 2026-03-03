# Setting up Rocq / Coq in Cursor (or VS Code)

This guide gets **Rocq** or **Coq** installed and compiling inside Cursor so you can run the [CoSProver-style workflow](ARCHITECTURE.md): edit `.v` files, see goals and errors, and use the coding agent for tactics.

---

## 1. Install Rocq or Coq

### Option A: Rocq (recommended for this project)

**Windows — binary installer (easiest):**

1. Go to [Rocq Platform releases](https://github.com/rocq-prover/platform/releases).
2. Download the Windows 64-bit installer, e.g.  
   `Coq-Platform-release-2025.01.0-version.8.20.2025.01-Windows-x86_64.exe`  
   or the 2024.10.0 release if you prefer.
3. Run the installer. It will install Coq/Rocq and add its `bin` directory to your PATH (or note the install path, e.g. `C:\Coq\bin` or under `Program Files`).
4. **Language server for the IDE:** The VsRocq extension needs `vsrocqtop`. The Windows installer may not include it. If after installing you don’t have `vsrocqtop`:
   - Use **WSL** (Windows Subsystem for Linux) and install via opam (see “Option A — Linux/WSL” below), then point the extension to the WSL path of `vsrocqtop`, **or**
   - Check the installer’s bin folder for `vsrocqtop.exe` or `coqtop.exe`; the extension can sometimes use `coqtop` with limited features.

**Linux / macOS / WSL — opam:**

```bash
# Create an opam switch (if you don’t have one)
opam init
eval $(opam env)

# Add Rocq repo and install
opam repo add rocq-released https://rocq-prover.org/opam/released
opam install rocq-prover vsrocq-language-server

# Confirm vsrocqtop is available
which vsrocqtop
```

Use the path printed by `which vsrocqtop` in the IDE settings below.

### Option B: Standard Coq (instead of Rocq)

- **Windows:** Use the [Coq Platform installer](https://github.com/coq/platform/releases) (from coq/platform, not rocq-prover). Then install the Coq language server (e.g. `opam install vscoq-language-server` in WSL and use that `vscoqtop`, or use the extension’s Coq path if the installer provides it).
- **Linux/macOS/WSL:** `opam install coq vscoq-language-server`, then `which vscoqtop`.

---

## 2. Install the IDE extension (Cursor / VS Code)

- **For Rocq:** Install **VsRocq**  
  - In Cursor: `Ctrl+Shift+X` → search **VsRocq** → Install **VsRocq** (publisher: rocq-prover).  
  - Or: [VS Code marketplace – VsRocq](https://marketplace.visualstudio.com/items?itemName=rocq-prover.vsrocq).
- **For Coq only:** Install **VsCoq** (e.g. **VsCoq** by coq-community or maximedenes) for Coq ≥ 8.18.

Use **one** of VsRocq or VsCoq, depending on whether you’re using Rocq or standard Coq.

---

## 3. Point the extension at the prover

The extension needs the full path to the language server executable.

- **Rocq:** `vsrocqtop` (or `vsrocqtop.exe` on Windows).
- **Coq:** `vscoqtop` (or `vscoqtop.exe` on Windows).

**In Cursor/VS Code:**

1. Open **File → Preferences → Settings** (or `Ctrl+,`).
2. Search for **Vsrocq** (or **VsCoq**).
3. Set:
   - **VsRocq: Path** (for Rocq) to the full path to `vsrocqtop`, e.g.  
     - Windows: `C:\Coq\bin\vsrocqtop.exe` or the path from your installer.  
     - WSL: `/home/yourname/.opam/default/bin/vsrocqtop`.
   - Or **VsCoq path** (for Coq) to the full path to `vscoqtop`.

**Workspace override (recommended for this repo):**

This project includes a `.vscode/settings.json` that you can edit so only this folder uses your Rocq/Coq path. Open the workspace folder in Cursor, then edit:

- `.vscode/settings.json`

Set either:

- `"vsrocq.path": "C:\\path\\to\\vsrocqtop.exe"` (Rocq), or  
- the equivalent Coq path if you use VsCoq.

Use double backslashes in JSON on Windows. Restart Cursor or reload the window (`Ctrl+Shift+P` → “Developer: Reload Window”) after changing the path.

---

## 4. Open the project as a folder and compile

1. In Cursor, use **File → Open Folder** and open the **RocqCoSPOC** project directory (the one that contains `_CoqProject` and your `.v` files).  
   Do **not** open a single `.v` file; the extension needs the folder and `_CoqProject` to resolve dependencies and compile.
2. Open a `.v` file (e.g. `coq/Example.v`). The extension should start the language server and check the file.
3. Use the proof commands (e.g. “Step forward”, “Interpret to point”) from the editor toolbar or command palette (`Ctrl+Shift+P` → “VsRocq” or “VsCoq”).

**If you see “Could not start coqtop/vsrocqtop”:**

- Confirm the path in settings is correct and that the executable runs in a terminal:  
  `& "C:\path\to\vsrocqtop.exe" -v` (PowerShell) or `vsrocqtop -v` (if on PATH).
- If you use the Windows Coq/Rocq installer and don’t have `vsrocqtop`, use the opam/WSL route and set **VsRocq: Path** to the WSL path of `vsrocqtop`, or install the language server as suggested in the extension’s docs.

---

## 5. Optional: compile from the terminal

From the project root (where `_CoqProject` is):

```bash
# If coqc is on your PATH (e.g. after Rocq/Coq Platform install):
coqc -R coq RocqCoSPOC coq/Example.v
```

Or use the Coq/Rocq Makefile if you add one (e.g. generated by `coq_makefile -f _CoqProject -o Makefile`).

---

## Summary

| Step | Rocq | Coq |
|------|------|-----|
| Install | Rocq Platform Windows installer or opam (rocq-prover + vsrocq-language-server) | Coq Platform or opam (coq + vscoq-language-server) |
| Extension | VsRocq (rocq-prover.vsrocq) | VsCoq |
| Setting | `vsrocq.path` → full path to `vsrocqtop` | Coq/VsCoq path → full path to `vscoqtop` |
| Project | Open **folder**; ensure `_CoqProject` exists | Same |

After this, you can run the three-step CoSProver-style workflow: rewrite (ChatGPT) → chain of states (Gemini) → tactics in the IDE with Rocq/Coq giving errors and goals directly.

---

## 6. Agent proof checking (optional)

The coding agent in this repo can apply tactics to `.v` files and **run the proof checker** to confirm proofs are valid. From the project root it runs:

- **PowerShell:** `.\scripts\check-proofs.ps1` — compiles all `.v` files listed in `_CoqProject` using `coqc`. Add new `.v` files to `_CoqProject` and they will be checked automatically.
- **Direct:** `coqc -R coq RocqCoSPOC coq/Example.v` (and similarly for other files).

So the agent can edit tactics, run the script (or `coqc`), read success or error output, and fix proofs until they pass.
