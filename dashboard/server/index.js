import cors from "cors";
import express from "express";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
const tracesDir = path.join(repoRoot, "pipeline", "traces");
const dashboardRunsDir = path.join(repoRoot, "pipeline", "dashboard-runs");
const jobs = new Map();

fs.mkdirSync(tracesDir, { recursive: true });
fs.mkdirSync(dashboardRunsDir, { recursive: true });

const app = express();
app.use(cors());
app.use(express.json({ limit: "2mb" }));

function listTraceFiles() {
  if (!fs.existsSync(tracesDir)) {
    return [];
  }
  return fs
    .readdirSync(tracesDir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => {
      const full = path.join(tracesDir, name);
      const stat = fs.statSync(full);
      return {
        name,
        fullPath: full,
        size: stat.size,
        mtimeMs: stat.mtimeMs,
      };
    })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);
}

function readTraceByName(name) {
  const safeName = path.basename(name);
  if (!safeName.endsWith(".json")) {
    throw new Error("Trace name must be a .json file.");
  }
  const full = path.join(tracesDir, safeName);
  if (!fs.existsSync(full)) {
    return null;
  }
  const text = fs.readFileSync(full, "utf8");
  return JSON.parse(text);
}

function slugify(text) {
  return String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

function makeRunId(label) {
  const stem = slugify(label) || "dashboard-run";
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  return `${stem}-${stamp}-${randomUUID().slice(0, 8)}`;
}

function normalizeLineEndings(text) {
  return String(text || "").replace(/\r\n/g, "\n");
}

function ensureTrailingPeriod(text) {
  const trimmed = text.trim();
  if (!trimmed) {
    return trimmed;
  }
  return /[.]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

function normalizeFormalSource(formalSourceInput, theoremName) {
  let text = normalizeLineEndings(formalSourceInput).trim();
  if (!text) {
    throw new Error("Formal theorem source is required.");
  }

  const proofIndex = text.search(/^\s*Proof\.\s*$/m);
  if (proofIndex >= 0) {
    text = text.slice(0, proofIndex).trimEnd();
  }
  text = text.replace(/^\s*Qed\.\s*$/gm, "").trim();

  const theoremDeclRe = /^\s*(Theorem|Lemma|Example|Corollary|Proposition|Remark|Fact|Goal)\b/m;
  if (!theoremDeclRe.test(text)) {
    text = `Theorem ${theoremName} : ${ensureTrailingPeriod(text)}`;
  }

  return `${text.trimEnd()}\nProof.\n`;
}

function appendLog(job, key, chunk) {
  const text = chunk.toString("utf8");
  const next = `${job[key]}${text}`;
  job[key] = next.length > 20000 ? next.slice(-20000) : next;
  job.updatedAt = new Date().toISOString();
}

function toRepoRelative(fullPath) {
  return path.relative(repoRoot, fullPath).replace(/\\/g, "/");
}

function serializeJob(job) {
  return {
    id: job.id,
    runLabel: job.runLabel,
    status: job.status,
    startedAt: job.startedAt,
    updatedAt: job.updatedAt,
    endedAt: job.endedAt ?? null,
    exitCode: job.exitCode,
    signal: job.signal ?? null,
    pid: job.pid ?? null,
    traceName: job.traceName,
    targetPath: job.targetPath,
    formalPath: job.formalPath,
    informalPath: job.informalPath,
    stdout: job.stdout,
    stderr: job.stderr,
  };
}

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, tracesDir, dashboardRunsDir, activeJobs: jobs.size });
});

app.get("/api/traces", (_req, res) => {
  const files = listTraceFiles().map((f) => ({
    name: f.name,
    size: f.size,
    updatedAt: new Date(f.mtimeMs).toISOString(),
  }));
  res.json({ tracesDir, files });
});

app.get("/api/traces/:name", (req, res) => {
  try {
    const trace = readTraceByName(req.params.name);
    if (!trace) {
      res.status(404).json({ error: "Trace file not found." });
      return;
    }
    res.json({ name: path.basename(req.params.name), trace });
  } catch (e) {
    res.status(400).json({ error: String(e.message || e) });
  }
});

app.get("/api/runs", (_req, res) => {
  const allJobs = [...jobs.values()]
    .sort((a, b) => String(b.startedAt).localeCompare(String(a.startedAt)))
    .map(serializeJob);
  res.json({ jobs: allJobs });
});

app.get("/api/runs/:id", (req, res) => {
  const job = jobs.get(req.params.id);
  if (!job) {
    res.status(404).json({ error: "Run not found." });
    return;
  }
  res.json({ job: serializeJob(job) });
});

app.post("/api/runs", (req, res) => {
  const informalProof = String(req.body?.informalProof || "").trim();
  const formalSourceInput = String(req.body?.formalSource || "").trim();
  const runLabelInput = String(req.body?.runLabel || "").trim();

  if (!informalProof) {
    res.status(400).json({ error: "Informal proof is required." });
    return;
  }
  if (!formalSourceInput) {
    res.status(400).json({ error: "Formal theorem statement or source is required." });
    return;
  }

  const runId = makeRunId(runLabelInput);
  const theoremName = `dashboard_${runId.replace(/[^a-zA-Z0-9_]/g, "_")}`;
  const targetFileName = `_dashboard_${runId.replace(/[^a-zA-Z0-9_]/g, "_")}.v`;
  const informalPath = path.join(dashboardRunsDir, `${runId}-informal.txt`);
  const targetPath = path.join(repoRoot, targetFileName);
  const traceName = `${runId}.json`;
  const tracePath = path.join(tracesDir, traceName);

  let formalSource;
  try {
    formalSource = normalizeFormalSource(formalSourceInput, theoremName);
  } catch (e) {
    res.status(400).json({ error: String(e.message || e) });
    return;
  }

  fs.writeFileSync(informalPath, `${normalizeLineEndings(informalProof).trimEnd()}\n`, "utf8");
  fs.writeFileSync(targetPath, formalSource, "utf8");

  const pythonExe = process.env.PYTHON || "python";
  const args = [
    "pipeline/run.py",
    "--informal",
    toRepoRelative(informalPath),
    "--formal",
    targetFileName,
    "--target",
    targetFileName,
    "--trace-out",
    toRepoRelative(tracePath),
  ];

  const job = {
    id: runId,
    runLabel: runLabelInput || runId,
    status: "starting",
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    endedAt: null,
    exitCode: null,
    signal: null,
    pid: null,
    traceName,
    targetPath: targetFileName,
    formalPath: targetFileName,
    informalPath: toRepoRelative(informalPath),
    stdout: "",
    stderr: "",
  };
  jobs.set(runId, job);

  const child = spawn(pythonExe, args, {
    cwd: repoRoot,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  child.on("spawn", () => {
    job.status = "running";
    job.pid = child.pid ?? null;
    job.updatedAt = new Date().toISOString();
  });

  child.stdout.on("data", (chunk) => appendLog(job, "stdout", chunk));
  child.stderr.on("data", (chunk) => appendLog(job, "stderr", chunk));

  child.on("error", (error) => {
    appendLog(job, "stderr", `\n${String(error.message || error)}\n`);
    job.status = "failed";
    job.exitCode = -1;
    job.endedAt = new Date().toISOString();
    job.updatedAt = job.endedAt;
  });

  child.on("close", (code, signal) => {
    job.exitCode = code;
    job.signal = signal ?? null;
    job.status = code === 0 ? "completed" : "failed";
    job.endedAt = new Date().toISOString();
    job.updatedAt = job.endedAt;
  });

  res.status(201).json({ job: serializeJob(job) });
});

const port = Number(process.env.PORT || 8787);
app.listen(port, () => {
  console.log(`Trace API listening on http://localhost:${port}`);
});
