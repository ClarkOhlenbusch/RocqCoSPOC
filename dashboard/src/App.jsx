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

function StateBlock({ title, content }) {
  return (
    <details className="state-block">
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

function isSkeletonTrace(trace) {
  return trace && (trace.skeleton != null || trace.fills != null);
}

function App() {
  const [files, setFiles] = useState([]);
  const [selectedName, setSelectedName] = useState("");
  const [trace, setTrace] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
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

  const summary = useMemo(() => {
    if (!trace) return null;
    if (isSkeletonTrace(trace)) {
      const fills = trace.fills || [];
      const totalAttempts = fills.length;
      const succeeded = fills.filter((fill) => fill.status === "success").length;
      const failed = fills.filter((fill) => fill.status === "compile_error" || fill.status === "model_error").length;
      const xmlFeedbackAttempts = fills.filter((fill) => (fill.compiler_feedback || []).length > 0).length;
      return {
        mode: "Skeleton + Fill",
        admitsFilled: trace.summary?.admits_filled ?? succeeded,
        totalAttempts: trace.summary?.total_attempts ?? totalAttempts,
        failedAttempts: failed,
        xmlFeedbackAttempts,
      };
    }

    const transitionCount = trace.summary?.transition_count ?? trace.transitions?.length ?? 0;
    const etr = trace.summary?.etr_retries ?? 0;
    const esr = trace.summary?.esr_retries ?? 0;
    const attempts = (trace.transitions || []).flatMap((transition) => transition.attempts || []);
    const modelAttempts = attempts.filter((attempt) => attempt.tactic_source === "model").length;
    const fallbackAttempts = attempts.filter((attempt) => attempt.tactic_source === "heuristic_fallback").length;
    return {
      mode: "Legacy (transitions)",
      transitionCount,
      etr,
      esr,
      modelAttempts,
      fallbackAttempts,
    };
  }, [trace]);

  const runStatus = activeRun?.status || "idle";
  const skeleton = isSkeletonTrace(trace);

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

      {trace && (
        <>
          <section className="panel summary-grid">
            <SummaryCard label="Status" value={trace.status || "unknown"} />
            <SummaryCard label="Mode" value={summary?.mode || "unknown"} />
            {skeleton ? (
              <>
                <SummaryCard label="Admits Filled" value={summary?.admitsFilled} />
                <SummaryCard label="Total Attempts" value={summary?.totalAttempts} />
                <SummaryCard label="Failed Attempts" value={summary?.failedAttempts} />
                <SummaryCard label="XML Feedback Attempts" value={summary?.xmlFeedbackAttempts} />
              </>
            ) : (
              <>
                <SummaryCard label="Transitions" value={summary?.transitionCount} />
                <SummaryCard label="Model Attempts" value={summary?.modelAttempts} />
                <SummaryCard label="Fallback Attempts" value={summary?.fallbackAttempts} />
                <SummaryCard label="ETR Retries" value={summary?.etr} />
                <SummaryCard label="ESR Retries" value={summary?.esr} />
              </>
            )}
          </section>

          <section className="panel">
            <h2>Step 1 - Rewrite</h2>
            <pre>{trace.rewrite?.text || "(missing rewrite text)"}</pre>
          </section>

          {skeleton ? (
            <section className="panel">
              <h2>Step 2 - Skeleton</h2>
              {trace.skeleton?.compiles != null && (
                <p>
                  Skeleton compiles: <strong>{trace.skeleton.compiles ? "Yes" : "No"}</strong>
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
              <pre>{trace.skeleton?.text || "(missing skeleton)"}</pre>
            </section>
          ) : (
            <section className="panel">
              <h2>Step 2 - Proof Goal</h2>
              <p>Direct proving (initial goal -&gt; No Goals)</p>
              {(trace.goal_sequence?.states || []).map((stateText, idx) => (
                <StateBlock key={idx} title={idx === 0 ? "Initial Goal" : "Target"} content={stateText} />
              ))}
            </section>
          )}

          {skeleton ? (
            <section className="panel">
              <h2>Step 3 - Fill Admits</h2>
              {(trace.fills || []).length === 0 && <p>(no fills yet)</p>}
              {(trace.fills || []).map((fill, idx) => (
                <details key={`${fill.admit_index ?? "unknown"}-${fill.attempt ?? idx}-${idx}`} className="transition-block">
                  <summary>
                    Admit #{fill.admit_index != null ? fill.admit_index + 1 : idx + 1} | Attempt {fill.attempt}
                    {" | "}
                    {fill.status || "pending"}
                    {fill.exit_code != null && ` | exit ${fill.exit_code}`}
                  </summary>
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
          ) : (
            <section className="panel">
              <h2>Step 3 - Transitions</h2>
              {(trace.transitions || []).map((transition) => (
                <details key={transition.transition_index} className="transition-block">
                  <summary>
                    Transition {transition.transition_index} ({transition.from_state_index} -&gt; {transition.to_state_index}) |{" "}
                    {transition.status}
                  </summary>
                  <StateBlock title="Expected From State" content={transition.from_state} />
                  <StateBlock title="Expected To State" content={transition.to_state} />
                  {(transition.attempts || []).map((attempt) => (
                    <details key={attempt.attempt} className="attempt-block">
                      <summary>
                        Attempt {attempt.attempt} | {attempt.status || "unknown"} | source: {attempt.tactic_source || "n/a"}
                      </summary>
                      {"tactic" in attempt && <StateBlock title="Tactic" content={attempt.tactic} />}
                      {"etr_tactic" in attempt && <StateBlock title="ETR Tactic" content={attempt.etr_tactic} />}
                      {"esr_tactic" in attempt && <StateBlock title="ESR Tactic" content={attempt.esr_tactic} />}
                      {"actual_state" in attempt && <StateBlock title="Actual State" content={attempt.actual_state} />}
                      {"check_stdout" in attempt && <StateBlock title="check-target stdout" content={attempt.check_stdout} />}
                      {"check_stderr" in attempt && <StateBlock title="check-target stderr" content={attempt.check_stderr} />}
                      {"error" in attempt && <StateBlock title="Error" content={attempt.error} />}
                    </details>
                  ))}
                </details>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}

export default App;
