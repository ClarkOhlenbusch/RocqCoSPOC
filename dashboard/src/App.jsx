import { useMemo, useState } from "react";
import "./App.css";

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

function App() {
  const [files, setFiles] = useState([]);
  const [selectedName, setSelectedName] = useState("");
  const [trace, setTrace] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadTraceList() {
    setError("");
    try {
      const res = await fetch("/api/traces");
      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }
      const data = await res.json();
      setFiles(data.files || []);
      if (!selectedName && data.files?.length) {
        setSelectedName(data.files[0].name);
      }
    } catch (e) {
      setError(`Failed to load trace list: ${e}`);
    }
  }

  async function openSelectedTrace() {
    if (!selectedName) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/traces/${encodeURIComponent(selectedName)}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Unknown error");
      }
      setTrace(data.trace);
    } catch (e) {
      setError(`Failed to load trace: ${e}`);
    } finally {
      setLoading(false);
    }
  }

  const summary = useMemo(() => {
    if (!trace) return null;
    const transitionCount = trace.summary?.transition_count ?? trace.transitions?.length ?? 0;
    const etr = trace.summary?.etr_retries ?? 0;
    const esr = trace.summary?.esr_retries ?? 0;
    return { transitionCount, etr, esr };
  }, [trace]);

  return (
    <div className="container">
      <header className="header">
        <h1>CoS Pipeline Dashboard</h1>
        <p>Visualize rewrite, chain-of-states, and transition retries from JSON traces.</p>
      </header>

      <section className="panel controls">
        <button onClick={loadTraceList}>Refresh Trace List</button>
        <select value={selectedName} onChange={(e) => setSelectedName(e.target.value)}>
          <option value="">Select a trace...</option>
          {files.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name}
            </option>
          ))}
        </select>
        <button onClick={openSelectedTrace} disabled={!selectedName || loading}>
          {loading ? "Loading..." : "Open Trace"}
        </button>
      </section>

      {error && <section className="panel error">{error}</section>}

      {trace && (
        <>
          <section className="panel summary-grid">
            <SummaryCard label="Status" value={trace.status || "unknown"} />
            <SummaryCard label="Mode" value="Direct" />
            <SummaryCard label="Transitions" value={summary.transitionCount} />
            <SummaryCard label="ETR Retries" value={summary.etr} />
            <SummaryCard label="ESR Retries" value={summary.esr} />
          </section>

          <section className="panel">
            <h2>Step 1 - Rewrite Output</h2>
            <pre>{trace.rewrite?.text || "(missing rewrite text)"}</pre>
          </section>

          <section className="panel">
            <h2>Step 2 - Proof Goal</h2>
            <p>Direct proving (State 0 → No Goals)</p>
            {(trace.chain_of_states?.states || []).map((stateText, idx) => (
              <StateBlock key={idx} title={idx === 0 ? "Initial Goal" : "Target"} content={stateText} />
            ))}
          </section>

          <section className="panel">
            <h2>Step 3 - Transitions</h2>
            {(trace.transitions || []).map((t) => (
              <details key={t.transition_index} className="transition-block">
                <summary>
                  Transition {t.transition_index} ({t.from_state_index} -&gt; {t.to_state_index}) |{" "}
                  {t.status}
                </summary>
                <StateBlock title="Expected From State" content={t.from_state} />
                <StateBlock title="Expected To State" content={t.to_state} />
                {(t.attempts || []).map((a) => (
                  <details key={a.attempt} className="attempt-block">
                    <summary>
                      Attempt {a.attempt} | {a.status || "unknown"}
                    </summary>
                    {"tactic" in a && <StateBlock title="Tactic" content={a.tactic} />}
                    {"etr_tactic" in a && <StateBlock title="ETR Tactic" content={a.etr_tactic} />}
                    {"esr_tactic" in a && <StateBlock title="ESR Tactic" content={a.esr_tactic} />}
                    {"actual_state" in a && <StateBlock title="Actual State" content={a.actual_state} />}
                    {"check_stdout" in a && <StateBlock title="check-target stdout" content={a.check_stdout} />}
                    {"check_stderr" in a && <StateBlock title="check-target stderr" content={a.check_stderr} />}
                    {"error" in a && <StateBlock title="Error" content={a.error} />}
                  </details>
                ))}
              </details>
            ))}
          </section>
        </>
      )}
    </div>
  );
}

export default App;
