import cors from "cors";
import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
const tracesDir = path.join(repoRoot, "pipeline", "traces");

const app = express();
app.use(cors());
app.use(express.json());

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

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, tracesDir });
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
  const requested = req.params.name;
  const safeName = path.basename(requested);
  if (!safeName.endsWith(".json")) {
    res.status(400).json({ error: "Trace name must be a .json file." });
    return;
  }
  const full = path.join(tracesDir, safeName);
  if (!fs.existsSync(full)) {
    res.status(404).json({ error: "Trace file not found." });
    return;
  }
  try {
    const text = fs.readFileSync(full, "utf8");
    const trace = JSON.parse(text);
    res.json({ name: safeName, trace });
  } catch (e) {
    res.status(500).json({ error: `Failed to read trace: ${e}` });
  }
});

const port = Number(process.env.PORT || 8787);
app.listen(port, () => {
  console.log(`Trace API listening on http://localhost:${port}`);
});
