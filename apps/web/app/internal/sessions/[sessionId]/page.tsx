"use client";

import { FormEvent, use, useState } from "react";
import { ApiError, getInternalSession, InternalSession } from "@/lib/api";

export default function InternalSessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const [token, setToken] = useState("");
  const [audit, setAudit] = useState<InternalSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadAudit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setAudit(await getInternalSession(sessionId, token.trim()));
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 401
        ? "The audit token was not accepted."
        : caught instanceof Error ? caught.message : "The audit session could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <div className="content-column audit-column">
        <p className="kicker">INTERNAL JOURNEY</p>
        <h1>Session audit</h1>
        <p className="lede">Protected developer view for session <code>{sessionId}</code>.</p>
        {!audit && (
          <form className="audit-auth" onSubmit={loadAudit}>
            <label htmlFor="audit-token">Internal audit token</label>
            <input id="audit-token" type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" />
            <button className="button button-primary" type="submit" disabled={!token.trim() || loading}>{loading ? "Loading..." : "Load session"}</button>
            {error && <p className="notice notice-error" role="alert">{error}</p>}
          </form>
        )}
        {audit && <AuditContent audit={audit} />}
      </div>
    </main>
  );
}

function AuditContent({ audit }: { audit: InternalSession }) {
  return (
    <>
      <section className="audit-summary" aria-labelledby="audit-summary-title">
        <h2 id="audit-summary-title">Session overview</h2>
        <dl className="audit-facts">
          <div><dt>Status</dt><dd>{audit.status}</dd></div>
          <div><dt>Started</dt><dd>{new Date(audit.started_at).toLocaleString()}</dd></div>
          <div><dt>Last activity</dt><dd>{new Date(audit.last_activity_at).toLocaleString()}</dd></div>
          <div><dt>Questions</dt><dd>{audit.questions.length}</dd></div>
          <div><dt>Snapshots</dt><dd>{audit.snapshots.length}</dd></div>
          <div><dt>AI runs</dt><dd>{audit.ai_runs.length}</dd></div>
        </dl>
      </section>

      <section className="audit-section" aria-labelledby="timeline-title">
        <h2 id="timeline-title">Journey timeline</h2>
        <ol className="audit-timeline">
          {audit.timeline.map((entry, index) => (
            <li key={`${entry.occurred_at}-${entry.kind}-${index}`}>
              <time dateTime={entry.occurred_at}>{new Date(entry.occurred_at).toLocaleString()}</time>
              <strong>{entry.label}</strong>
              <pre>{JSON.stringify(entry.details, null, 2)}</pre>
            </li>
          ))}
        </ol>
      </section>

      <AuditList title="Profile snapshots" items={audit.snapshots} />
      <AuditList title="AI runs" items={audit.ai_runs} />
      <AuditList title="Responses" items={audit.responses} />
      <AuditList title="Analytics events" items={audit.events} />
    </>
  );
}

function AuditList({ title, items }: { title: string; items: Array<Record<string, unknown>> }) {
  return (
    <section className="audit-section" aria-labelledby={`${title}-title`}>
      <h2 id={`${title}-title`}>{title}</h2>
      {items.length === 0 ? <p className="microcopy">None recorded.</p> : (
        <div className="audit-list">
          {items.map((item, index) => <pre key={index}>{JSON.stringify(item, null, 2)}</pre>)}
        </div>
      )}
    </section>
  );
}
