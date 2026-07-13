"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AnswerValue,
  ApiError,
  getSession,
  QuestionnaireSession,
  restartSession,
  retrySession,
  recordQuestionDeployed,
  startSession,
  submitAnswer,
} from "@/lib/api";

const SESSION_KEY = "roomicheck_session_id";

const DIMENSION_LABELS: Record<string, string> = {
  noise_environment: "Noise and environment",
  social_interaction: "Social interaction",
  study_daily_routine: "Study and daily routine",
  cultural_openness: "Cultural openness",
  household_structure: "Household structure",
  communication_conflict: "Communication and conflict",
};

const DIMENSION_IDS = [
  "noise_environment",
  "social_interaction",
  "study_daily_routine",
  "cultural_openness",
  "household_structure",
  "communication_conflict",
] as const;

type ProfileDimension = {
  score: number | null;
  label: string | null;
  confidence: number;
  coverage: string;
  summary: string | null;
  unknowns: string[];
};

type FinalProfile = {
  dimensions?: Record<string, ProfileDimension>;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return "This session has moved on. Refreshing the current question…";
    if (error.status === 503) return "The service is temporarily unavailable. Please try again in a moment.";
    return error.message;
  }
  return error instanceof Error ? error.message : fallback;
}

function profileDimensions(profile: Record<string, unknown> | null): Array<[string, ProfileDimension]> {
  const dimensions = (profile as FinalProfile | null)?.dimensions;
  return DIMENSION_IDS.map((id) => {
    const dimension = dimensions?.[id];
    return [id, {
      score: typeof dimension?.score === "number" ? dimension.score : null,
      label: typeof dimension?.label === "string" ? dimension.label : null,
      confidence: typeof dimension?.confidence === "number" ? dimension.confidence : 0,
      coverage: typeof dimension?.coverage === "string" ? dimension.coverage : "unknown",
      summary: typeof dimension?.summary === "string" ? dimension.summary : null,
      unknowns: Array.isArray(dimension?.unknowns) ? dimension.unknowns.filter((value): value is string => typeof value === "string") : [],
    }] as [string, ProfileDimension];
  });
}

export default function Home() {
  const [session, setSession] = useState<QuestionnaireSession | null>(null);
  const [answer, setAnswer] = useState("");
  const [otherAnswer, setOtherAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const question = session?.current_question ?? null;
  const isRetry = session?.status === "needs_retry";
  const isProcessing = session?.status === "processing";

  useEffect(() => {
    let cancelled = false;
    const sessionId = window.localStorage.getItem(SESSION_KEY);
    if (!sessionId) {
      queueMicrotask(() => setLoading(false));
      return () => { cancelled = true; };
    }

    getSession(sessionId)
      .then((saved) => {
        if (!cancelled) setSession(saved);
      })
      .catch(() => {
        window.localStorage.removeItem(SESSION_KEY);
        if (!cancelled) setError("Your saved session could not be restored. You can start a new one.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!session?.session_id || session.status !== "processing") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const refresh = async () => {
      try {
        const updated = await getSession(session.session_id);
        if (cancelled) return;
        setSession(updated);
        if (updated.status === "processing") timer = setTimeout(refresh, 1200);
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught, "We could not check processing status."));
      }
    };

    timer = setTimeout(refresh, 1200);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [session?.session_id, session?.status]);

  useEffect(() => {
    const sessionId = session?.session_id;
    if (!sessionId || !question || session.status === "complete") return;
    recordQuestionDeployed(sessionId, question.id).catch(() => undefined);
  }, [question, session?.session_id, session?.status]);

  const selectedAnswer = useMemo<AnswerValue | null>(() => {
    if (!question) return null;
    return {
      free_text: ["free_text", "scenario"].includes(question.question_type)
        ? answer.trim()
        : question.question_type === "single_choice" && answer === "other"
          ? otherAnswer.trim()
          : null,
      scale_value: question.question_type === "scale" ? Number(answer) : null,
      selected_option_id: question.question_type === "single_choice" ? answer || null : null,
    };
  }, [answer, otherAnswer, question]);

  const canSubmit = Boolean(
    session && (isRetry || (selectedAnswer && (
      selectedAnswer.free_text || selectedAnswer.scale_value || selectedAnswer.selected_option_id
    )))
  );

  async function begin() {
    setLoading(true);
    setError(null);
    try {
      const created = await startSession();
      window.localStorage.setItem(SESSION_KEY, created.session_id);
      setSession(created);
    } catch (caught) {
      setError(errorMessage(caught, "Unable to start RoomiCheck."));
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || submitting || !canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = isRetry
        ? await retrySession(session.session_id)
        : await submitAnswer(session.session_id, question!.id, selectedAnswer!);
      setSession(updated);
      setAnswer("");
      setOtherAnswer("");
    } catch (caught) {
      setError(errorMessage(caught, "We could not save that response."));
      if (caught instanceof ApiError && caught.status === 409) {
        const refreshed = await getSession(session.session_id).catch(() => null);
        if (refreshed) setSession(refreshed);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function restart() {
    if (!session || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await restartSession(session.session_id);
      window.localStorage.setItem(SESSION_KEY, created.session_id);
      setSession(created);
      setAnswer("");
      setOtherAnswer("");
    } catch (caught) {
      setError(errorMessage(caught, "We could not start a new session."));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingScreen label="Restoring your session" />;

  if (!session) {
    return (
      <main className="shell shell-center">
        <section className="panel hero-panel" aria-labelledby="welcome-title">
          <p className="kicker">ROOMICHECK</p>
          <h1 id="welcome-title">Describe how home works best for you.</h1>
          <p className="lede">Answer a short adaptive questionnaire and receive an explainable co-living preference profile.</p>
          <div className="hero-actions">
            <button className="button button-primary" onClick={begin} disabled={loading}>
              Start questionnaire
            </button>
            <p className="microcopy">No account required. Your progress is saved in this browser.</p>
          </div>
          {error && <ErrorNotice message={error} />}
        </section>
      </main>
    );
  }

  if (session.status === "complete") {
    return <CompletionView session={session} loading={submitting} onRestart={restart} error={error} />;
  }

  if (isProcessing) {
    return (
      <main className="shell shell-center">
        <section className="panel status-panel" aria-labelledby="processing-title" aria-live="polite">
          <span className="status-mark" aria-hidden="true">...</span>
          <p className="kicker">PROCESSING</p>
          <h1 id="processing-title">We are shaping your next question.</h1>
          <p className="lede">Your answer is saved. RoomiCheck is interpreting it and choosing the most useful follow-up.</p>
          <div className="progress-indicator" aria-label="Processing" role="progressbar" />
          {error && (
            <>
              <ErrorNotice message={error} />
              <button className="button button-secondary" onClick={() => window.location.reload()}>Refresh session</button>
            </>
          )}
        </section>
      </main>
    );
  }

  if (!question) {
    return (
      <main className="shell shell-center">
        <section className="panel status-panel" aria-labelledby="unavailable-title">
          <p className="kicker">ONE MOMENT</p>
          <h1 id="unavailable-title">The next question is not ready yet.</h1>
          <p className="lede">Refresh the session to continue. Your saved answers are still safe.</p>
          <button className="button button-secondary" onClick={() => window.location.reload()}>Refresh session</button>
          {error && <ErrorNotice message={error} />}
        </section>
      </main>
    );
  }

  return (
    <main className="shell questionnaire-shell">
      <div className="content-column">
        <header className="topbar">
          <p className="kicker">ROOMICHECK</p>
          <button className="text-button" onClick={restart} disabled={submitting}>Start over</button>
        </header>

        <section className="progress-block" aria-label="Questionnaire progress">
          <div className="progress-meta">
            <span>Question {question.order} of {session.progress.maximum}</span>
            <span>{session.progress.answered} answered</span>
          </div>
          <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={session.progress.maximum} aria-valuenow={session.progress.answered} aria-label={`${session.progress.answered} of ${session.progress.maximum} questions answered`}>
            <span style={{ width: `${Math.min(100, (session.progress.answered / session.progress.target_maximum) * 100)}%` }} />
          </div>
        </section>

        <section className="question-panel" aria-labelledby="question-title">
          {isRetry && (
            <div className="notice notice-info" role="status">
              <strong>Your answer is safe.</strong> We are retrying the saved response; you do not need to enter it again.
            </div>
          )}
          <h1 id="question-title">{question.text}</h1>
          <form onSubmit={submit}>

            {["free_text", "scenario"].includes(question.question_type) && (
              <div className="field-group">
                <label htmlFor="free-response">Your response</label>
                <textarea id="free-response" value={answer} onChange={(event) => setAnswer(event.target.value)} maxLength={4000} rows={7} autoFocus={!isRetry} disabled={isRetry || submitting} />
                <span className="field-hint">{answer.length}/4000 characters</span>
              </div>
            )}

            {question.question_type === "scale" && (
              <fieldset className="choice-fieldset">
                <legend className="sr-only">Choose a value from {question.scale_min} to {question.scale_max}</legend>
                <div className="scale-grid">
                  {Array.from({ length: (question.scale_max ?? 5) - (question.scale_min ?? 1) + 1 }, (_, index) => (question.scale_min ?? 1) + index).map((value) => (
                    <label className={`scale-option${answer === String(value) ? " is-selected" : ""}`} key={value}>
                      <input type="radio" name="scale-answer" value={value} checked={answer === String(value)} onChange={(event) => setAnswer(event.target.value)} disabled={submitting} />
                      <span>{value}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

            {question.question_type === "single_choice" && (
              <fieldset className="choice-fieldset">
                <legend className="sr-only">Available responses</legend>
                <div className="option-list">
                  {question.options.map((option) => (
                    <label className={`option-card${answer === option.id ? " is-selected" : ""}`} key={option.id}>
                      <input type="radio" name="choice-answer" value={option.id} checked={answer === option.id} onChange={(event) => setAnswer(event.target.value)} disabled={submitting} />
                      <span>{option.label}</span>
                    </label>
                  ))}
                </div>
                {answer === "other" && (
                  <div className="field-group other-field">
                    <label htmlFor="other-response">Tell us more</label>
                    <textarea id="other-response" value={otherAnswer} onChange={(event) => setOtherAnswer(event.target.value)} maxLength={4000} rows={4} autoFocus disabled={submitting} />
                  </div>
                )}
              </fieldset>
            )}

            <div className="form-footer">
              <button className="button button-primary button-wide" type="submit" disabled={!canSubmit || submitting}>
                {submitting ? "Saving your response..." : isRetry ? "Retry saved response" : "Continue"}
              </button>
            </div>
            {error && <ErrorNotice message={error} />}
          </form>
        </section>
      </div>
    </main>
  );
}

function LoadingScreen({ label }: { label: string }) {
  return (
    <main className="shell shell-center">
      <section className="panel status-panel" aria-live="polite">
        <span className="status-mark" aria-hidden="true">...</span>
        <p className="kicker">ROOMICHECK</p>
        <h1>{label}</h1>
        <div className="progress-indicator" aria-label={label} role="progressbar" />
      </section>
    </main>
  );
}

function ErrorNotice({ message }: { message: string }) {
  return <p className="notice notice-error" role="alert">{message}</p>;
}

function CompletionView({ session, loading, onRestart, error }: { session: QuestionnaireSession; loading: boolean; onRestart: () => void; error: string | null }) {
  const dimensions = profileDimensions(session.final_profile);
  return (
    <main className="shell">
      <div className="content-column completion-column">
        <header className="topbar">
          <p className="kicker">ROOMICHECK</p>
          <button className="text-button" onClick={onRestart} disabled={loading}>Start over</button>
        </header>
        <section className="completion-intro" aria-labelledby="complete-title">
          <h1 id="complete-title">Your co-living profile</h1>
        </section>
        <section className="summary-card" aria-labelledby="summary-title">
          <h2 id="summary-title">Your summary</h2>
          <p>{session.final_summary || "Your profile summary is ready."}</p>
        </section>
        {dimensions.length > 0 && (
          <section className="profile-section" aria-labelledby="dimensions-title">
            <div className="section-heading">
              <h2 id="dimensions-title">Six dimensions</h2>
              <p>Scores describe preferences, not whether someone is a good or bad roommate.</p>
            </div>
            <div className="dimension-grid">
              {dimensions.map(([id, dimension]) => (
                <article className="dimension-card" key={id}>
                  <div className="dimension-heading">
                    <h3>{DIMENSION_LABELS[id] ?? id.replaceAll("_", " ")}</h3>
                  </div>
                  <div className="score-row">
                    <span className="score-label">{dimension.label ?? "Not yet defined"}</span>
                    {typeof dimension.score === "number" && <strong>{dimension.score}/100</strong>}
                  </div>
                  <div className="score-track" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, dimension.score ?? 0))}%` }} /></div>
                  {dimension.summary && <p>{dimension.summary}</p>}
                  {dimension.unknowns?.length > 0 && <p className="uncertainty">Open question: {dimension.unknowns[0]}</p>}
                </article>
              ))}
            </div>
          </section>
        )}
        {error && <ErrorNotice message={error} />}
        <button className="button button-secondary button-wide" onClick={onRestart} disabled={loading}>{loading ? "Starting over..." : "Start a new profile"}</button>
      </div>
    </main>
  );
}
