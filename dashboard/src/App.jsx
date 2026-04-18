import { useEffect, useMemo, useState } from "react";
import "./App.css";

const ACTIVE_RUN_STATES = new Set(["starting", "running"]);

const INITIAL_FORM = {
  runLabel: "",
  formalSource: "",
  informalProof: "",
};

function SummaryCard({ label, value }) {
  return (
    <div className="summary-card">
      <div className="summary-label">{label}</div>
      <div className="summary-value">{value}</div>
    </div>
  );
}

function StateBlock({ title, content, open = false }) {
  return (
    <details className="state-block" open={open}>
      <summary>{title}</summary>
      <pre>{content || "(empty)"}</pre>
    </details>
  );
}

function formatCompilerFeedback(feedback) {
  if (!Array.isArray(feedback) || feedback.length === 0) {
    return "";
  }
  return feedback.map((entry) => `<${entry.tag}>\n${entry.content}\n</${entry.tag}>`).join("\n\n");
}

function App() {
  const [files, setFiles] = useState([]);
  const [selectedName, setSelectedName] = useState("");
  const [trace, setTrace] = useState(null);
  const [evalRuns, setEvalRuns] = useState([]);
  const [selectedEvalRun, setSelectedEvalRun] = useState("");
  const [evalSummary, setEvalSummary] = useState(null);
  const [selectedEvalCase, setSelectedEvalCase] = useState("");
  const [evalCaseDetail, setEvalCaseDetail] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingEvalRuns, setLoadingEvalRuns] = useState(false);
  const [loadingEvalSummary, setLoadingEvalSummary] = useState(false);
  const [loadingEvalCase, setLoadingEvalCase] = useState(false);
  const [startingRun, setStartingRun] = useState(false);
  const [activeRun, setActiveRun] = useState(null);
  const [form, setForm] = useState(INITIAL_FORM);

  async function loadTraceList() {
    try {
      const res = await fetch("/api/traces");
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setFiles(data.files || []);
      setSelectedName((current) => current || data.files?.[0]?.name || "");
    } catch (e) {
      setError(`Failed to load trace list: ${e}`);
    }
  }

  async function loadEvalRuns() {
    setLoadingEvalRuns(true);
    try {
      const res = await fetch("/api/evals");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || `Server returned ${res.status}`);
      }
      const runs = data.runs || [];
      setEvalRuns(runs);
      setSelectedEvalRun((current) => current || runs?.[0]?.name || "");
    } catch (e) {
      setError(`Failed to load eval runs: ${e}`);
    } finally {
      setLoadingEvalRuns(false);
    }
  }

  async function openEvalRun(runName = selectedEvalRun) {
    if (!runName) return;
    setLoadingEvalSummary(true);
    setError("");
    try {
      const res = await fetch(`/api/evals/${encodeURIComponent(runName)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || `Server returned ${res.status}`);
      }
      setEvalSummary(data);
      setEvalCaseDetail(null);
      const firstCase = data.cases?.[0]?.caseIndex;
      setSelectedEvalCase((current) => current || String(firstCase || ""));
    } catch (e) {
      setError(`Failed to load eval run: ${e}`);
    } finally {
      setLoadingEvalSummary(false);
    }
  }

  async function openEvalCase(caseIndex = selectedEvalCase) {
    if (!selectedEvalRun || !caseIndex) return;
    setLoadingEvalCase(true);
    setError("");
    try {
      const res = await fetch(
        `/api/evals/${encodeURIComponent(selectedEvalRun)}/cases/${encodeURIComponent(caseIndex)}`,
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || `Server returned ${res.status}`);
      }
      setEvalCaseDetail(data);
      setTrace(data.trace || null);
    } catch (e) {
      setError(`Failed to load eval case details: ${e}`);
    } finally {
      setLoadingEvalCase(false);
    }
  }

  async function fetchTraceByName(name, { silentNotFound = false, showLoading = false } = {}) {
    if (!name) return;
    if (showLoading) setLoading(true);
    try {
      const res = await fetch(`/api/traces/${encodeURIComponent(name)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (silentNotFound && res.status === 404) return;
        throw new Error(data.error || `Server returned ${res.status}`);
      }
      setTrace(data.trace);
    } catch (e) {
      if (!silentNotFound) {
        setError(`Failed to load trace: ${e}`);
      }
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  async function openSelectedTrace() {
    if (!selectedName) return;
    setError("");
    await fetchTraceByName(selectedName, { showLoading: true });
  }

  async function refreshRun(runId) {
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);
      setActiveRun(data.job);
      if (data.job.traceName) {
        setSelectedName(data.job.traceName);
        await fetchTraceByName(data.job.traceName, { silentNotFound: true });
      }
      if (!ACTIVE_RUN_STATES.has(data.job.status)) {
        await loadTraceList();
      }
    } catch (e) {
      setError(`Failed to refresh run status: ${e}`);
    }
  }

  async function startRun(event) {
    event.preventDefault();
    if (!form.formalSource.trim() || !form.informalProof.trim()) {
      setError("Formal theorem source and informal proof are both required.");
      return;
    }
    setStartingRun(true);
    setError("");
    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);
      setActiveRun(data.job);
      setSelectedName(data.job.traceName);
      setTrace(null);
      await loadTraceList();
      await refreshRun(data.job.id);
    } catch (e) {
      setError(`Failed to start pipeline run: ${e}`);
    } finally {
      setStartingRun(false);
    }
  }

  useEffect(() => {
    loadTraceList();
    loadEvalRuns();
  }, []);

  useEffect(() => {
    if (!activeRun?.id) return undefined;
    let cancelled = false;

    const tick = async () => {
      if (!cancelled) {
        await refreshRun(activeRun.id);
      }
    };

    tick();
    if (!ACTIVE_RUN_STATES.has(activeRun.status)) {
      return () => {
        cancelled = true;
      };
    }

    const interval = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [activeRun?.id, activeRun?.status]);

  const traceSummary = useMemo(() => {
    if (!trace) return null;
    const fills = trace.fills || [];
    const totalAttempts = fills.length;
    const succeeded = fills.filter((fill) => fill.status === "success").length;
    const failed = fills.filter((fill) => fill.status === "compile_error" || fill.status === "model_error").length;
    const xmlFeedbackAttempts = fills.filter((fill) => (fill.compiler_feedback || []).length > 0).length;
    const formatRetries = fills.reduce(
      (count, fill) => count + (fill.model_attempts || []).filter((attempt) => attempt.status === "invalid_format").length,
      0,
    );
    const modelAttempts = fills.filter((fill) => fill.source === "model").length;
    return {
      mode: "Skeleton + Fill",
      admitsFilled: trace.summary?.admits_filled ?? succeeded,
      totalAttempts: trace.summary?.total_attempts ?? totalAttempts,
      failedAttempts: failed,
      xmlFeedbackAttempts,
      formatRetries,
      modelAttempts,
    };
  }, [trace]);

  const runStatus = activeRun?.status || "idle";
  const supportsCurrentTrace = !trace || "skeleton" in trace || "fills" in trace;

  return (
    <div className="container">
      <header className="header">
        <h1>Proof Pipeline Dashboard</h1>
        <p>Launch a run, then inspect rewrite, skeleton, fill retries, and compiler feedback as the trace updates.</p>
      </header>

      <section className="panel">
        <h2>Start A Run</h2>
        <form className="run-form" onSubmit={startRun}>
          <div className="form-grid">
            <label className="field">
              <span>Run label</span>
              <input
                type="text"
                value={form.runLabel}
                onChange={(e) => setForm((current) => ({ ...current, runLabel: e.target.value }))}
                placeholder="Optional label for this run"
              />
            </label>

            <label className="field field-wide">
              <span>Formal theorem source</span>
              <textarea
                value={form.formalSource}
                onChange={(e) => setForm((current) => ({ ...current, formalSource: e.target.value }))}
                placeholder={
                  "Paste a theorem statement or full theorem header.\nIf you paste only a proposition, the dashboard will wrap it in a temporary theorem and add Proof."
                }
                rows={7}
              />
            </label>

            <label className="field field-wide">
              <span>Informal proof</span>
              <textarea
                value={form.informalProof}
                onChange={(e) => setForm((current) => ({ ...current, informalProof: e.target.value }))}
                placeholder="Paste the informal proof you want the pipeline to rewrite and prove."
                rows={10}
              />
            </label>
          </div>

          <div className="form-actions">
            <button type="submit" disabled={startingRun}>
              {startingRun ? "Starting..." : "Start Pipeline Run"}
            </button>
            <span className="helper-text">
              Creates a temporary theorem file, launches `pipeline/run.py`, and follows the trace.
            </span>
          </div>
        </form>
      </section>

      <section className="panel controls">
        <button onClick={loadTraceList}>Refresh Trace List</button>
        <select value={selectedName} onChange={(e) => setSelectedName(e.target.value)}>
          <option value="">Select a trace...</option>
          {files.map((file) => (
            <option key={file.name} value={file.name}>
              {file.name}
            </option>
          ))}
        </select>
        <button onClick={openSelectedTrace} disabled={!selectedName || loading}>
          {loading ? "Loading..." : "Open Trace"}
        </button>
      </section>

      <section className="panel">
        <h2>Browse Eval Results</h2>
        <div className="controls">
          <button onClick={loadEvalRuns} disabled={loadingEvalRuns}>
            {loadingEvalRuns ? "Refreshing..." : "Refresh Eval Runs"}
          </button>
          <select value={selectedEvalRun} onChange={(e) => setSelectedEvalRun(e.target.value)}>
            <option value="">Select an eval run...</option>
            {evalRuns.map((run) => (
              <option key={run.name} value={run.name}>
                {run.name}
              </option>
            ))}
          </select>
          <button onClick={() => openEvalRun()} disabled={!selectedEvalRun || loadingEvalSummary}>
            {loadingEvalSummary ? "Loading..." : "Open Eval Run"}
          </button>
        </div>

        {evalSummary && (
          <>
            <div className="run-meta">
              <span>Run: {evalSummary.runName}</span>
              <span>Dataset: {evalSummary.dataset || "unknown"}</span>
              <span>Split: {evalSummary.split || "unknown"}</span>
              <span>Generated: {evalSummary.generatedAt || "unknown"}</span>
            </div>
            <div className="summary-grid">
              <SummaryCard label="Cases" value={evalSummary.aggregate?.num_cases ?? evalSummary.numCases ?? 0} />
              <SummaryCard label="Successes" value={evalSummary.aggregate?.num_success ?? 0} />
              <SummaryCard label="Success Rate" value={evalSummary.aggregate?.success_rate ?? 0} />
              <SummaryCard label="Mean Runtime (s)" value={evalSummary.aggregate?.elapsed_sec_mean ?? 0} />
              <SummaryCard label="Total Runtime (s)" value={evalSummary.aggregate?.elapsed_sec_total ?? 0} />
              <SummaryCard label="Mean Fill Attempts" value={evalSummary.aggregate?.fill_attempts_mean ?? 0} />
            </div>

            <div className="controls">
              <select value={selectedEvalCase} onChange={(e) => setSelectedEvalCase(e.target.value)}>
                <option value="">Select a case...</option>
                {(evalSummary.cases || []).map((entry) => (
                  <option key={entry.caseIndex} value={String(entry.caseIndex)}>
                    {entry.caseIndex} - {entry.caseName} | {entry.traceStatus}
                  </option>
                ))}
              </select>
              <button onClick={() => openEvalCase()} disabled={!selectedEvalCase || loadingEvalCase}>
                {loadingEvalCase ? "Loading Case..." : "Open Case Details"}
              </button>
            </div>
          </>
        )}
      </section>

      {evalCaseDetail && (
        <section className="panel">
          <h2>
            Eval Case #{evalCaseDetail.case.caseIndex} - {evalCaseDetail.case.caseName}
          </h2>
          <div className="run-meta">
            <span>Status: {evalCaseDetail.case.traceStatus || "unknown"}</span>
            <span>Failure Stage: {evalCaseDetail.case.failureStage || "none"}</span>
            <span>Return Code: {evalCaseDetail.case.returnCode ?? "unknown"}</span>
            <span>Elapsed (s): {evalCaseDetail.case.elapsedSec ?? "unknown"}</span>
          </div>
          <StateBlock title="Command" content={(evalCaseDetail.case.command || []).join(" ")} />
          <StateBlock title="Informal input (.txt)" content={evalCaseDetail.artifacts?.informalText} open />
          <StateBlock title="Formal statement (.v)" content={evalCaseDetail.artifacts?.formalText} />
          <StateBlock title="Target proof file (.v)" content={evalCaseDetail.artifacts?.targetText} />
          <StateBlock title="Pipeline stdout" content={evalCaseDetail.artifacts?.stdoutText} />
          <StateBlock title="Pipeline stderr" content={evalCaseDetail.artifacts?.stderrText} />
          <StateBlock title="Raw trace JSON" content={JSON.stringify(evalCaseDetail.trace || {}, null, 2)} />
        </section>
      )}

      {error && <section className="panel error">{error}</section>}

      {activeRun && (
        <section className="panel">
          <h2>Active Run</h2>
          <div className="run-meta">
            <span className={`status-pill status-${runStatus}`}>Status: {runStatus}</span>
            <span>Trace: {activeRun.traceName}</span>
            <span>Target: {activeRun.targetPath}</span>
            {activeRun.pid && <span>PID: {activeRun.pid}</span>}
          </div>

          <div className="log-grid">
            <div>
              <h3>Pipeline stdout</h3>
              <pre>{activeRun.stdout || "(waiting for output)"}</pre>
            </div>
            <div>
              <h3>Pipeline stderr</h3>
              <pre>{activeRun.stderr || "(no stderr output)"}</pre>
            </div>
          </div>
        </section>
      )}

      {trace?.status === "failed" && trace?.error && <section className="panel error">{trace.error}</section>}

      {trace && !supportsCurrentTrace && (
        <section className="panel error">
          This trace does not use the current skeleton-and-fill format. Start a new run to inspect it here.
        </section>
      )}

      {trace && supportsCurrentTrace && (
        <>
          <section className="panel summary-grid">
            <SummaryCard label="Status" value={trace.status || "unknown"} />
            <SummaryCard label="Mode" value={traceSummary?.mode || "unknown"} />
            <SummaryCard label="Admits Filled" value={traceSummary?.admitsFilled} />
            <SummaryCard label="Total Attempts" value={traceSummary?.totalAttempts} />
            <SummaryCard label="Failed Attempts" value={traceSummary?.failedAttempts} />
            <SummaryCard label="XML Feedback Attempts" value={traceSummary?.xmlFeedbackAttempts} />
            <SummaryCard label="Format Retries" value={traceSummary?.formatRetries} />
            <SummaryCard label="Model Attempts" value={traceSummary?.modelAttempts} />
          </section>

          <section className="panel">
            <h2>Step 1 - Rewrite</h2>
            <pre>{trace.rewrite?.text || "(missing rewrite text)"}</pre>
          </section>

          <section className="panel">
            <h2>Step 2 - Skeleton</h2>
            {trace.skeleton?.compiles != null && (
              <p>
                Skeleton compiles: <strong>{trace.skeleton.compiles ? "Yes" : "No"}</strong>
              </p>
            )}
            {trace.skeleton?.full_file_text && (
              <StateBlock title="Full target file (lemma and proof)" content={trace.skeleton.full_file_text} open />
            )}
            {trace.skeleton?.proof_state != null && trace.skeleton.proof_state !== "" && (
              <StateBlock title="Proof state (first admit)" content={trace.skeleton.proof_state} open />
            )}
            {(trace.skeleton?.slot_names || []).length > 0 && trace.skeleton?.proof_state === "" && (
              <p className="helper-text">
                Proof state was not captured. Check that <code>scripts/get-proof-state.py</code> can run{" "}
                <code>coqtop</code> for this file.
              </p>
            )}
            {trace.skeleton?.check_stdout && (
              <StateBlock title="Skeleton compile stdout" content={trace.skeleton.check_stdout} />
            )}
            {trace.skeleton?.check_stderr && (
              <StateBlock title="Skeleton compile stderr" content={trace.skeleton.check_stderr} />
            )}
            {trace.skeleton?.compiler_feedback?.length > 0 && (
              <StateBlock
                title="Structured Compiler Feedback"
                content={formatCompilerFeedback(trace.skeleton.compiler_feedback)}
              />
            )}
            <details className="state-block" open={!trace.skeleton?.full_file_text}>
              <summary>Tactic skeleton only (proof body, no lemma)</summary>
              <pre>{trace.skeleton?.text || "(missing skeleton)"}</pre>
            </details>
          </section>

          <section className="panel">
            <h2>Step 3 - Fill Admits</h2>
            {(trace.fills || []).length === 0 && <p>(no fills yet)</p>}
            {(trace.fills || []).map((fill, idx) => (
              <details key={`${fill.admit_index ?? "unknown"}-${fill.attempt ?? idx}-${idx}`} className="transition-block">
                <summary>
                  Admit #{fill.admit_index != null ? fill.admit_index + 1 : idx + 1} | Attempt {fill.attempt}
                  {fill.slot_name ? ` | ${fill.slot_name}` : ""}
                  {" | "}
                  {fill.status || "pending"}
                  {fill.exit_code != null && ` | exit ${fill.exit_code}`}
                </summary>
                <p>Source: {fill.source || "unknown"}</p>
                {fill.current_goal_state && <StateBlock title="Current goal state" content={fill.current_goal_state} />}
                {(fill.model_attempts || []).map((modelAttempt) => (
                  <div key={modelAttempt.format_attempt}>
                    <StateBlock
                      title={`Model output (format attempt ${modelAttempt.format_attempt})`}
                      content={modelAttempt.raw_output}
                    />
                    {modelAttempt.error && (
                      <StateBlock
                        title={`Format error (attempt ${modelAttempt.format_attempt})`}
                        content={modelAttempt.error}
                      />
                    )}
                  </div>
                ))}
                {fill.replacement && <StateBlock title="Replacement tactics" content={fill.replacement} />}
                {fill.check_stdout && <StateBlock title="Compile stdout" content={fill.check_stdout} />}
                {fill.check_stderr && <StateBlock title="Compile stderr" content={fill.check_stderr} />}
                {fill.compiler_feedback?.length > 0 && (
                  <StateBlock
                    title="Structured Compiler Feedback"
                    content={formatCompilerFeedback(fill.compiler_feedback)}
                  />
                )}
                {fill.error && <StateBlock title="Error" content={fill.error} />}
              </details>
            ))}
          </section>
        </>
      )}
    </div>
  );
}

export default App;
