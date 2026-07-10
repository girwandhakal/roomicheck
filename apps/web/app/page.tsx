"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  AnswerValue,
  getSession,
  QuestionnaireSession,
  restartSession,
  startSession,
  submitAnswer,
} from "@/lib/api";

const SESSION_KEY = "roomicheck_session_id";

export default function Home() {
  const [session, setSession] = useState<QuestionnaireSession | null>(null);
  const [answer, setAnswer] = useState("");
  const [otherAnswer, setOtherAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sessionId = window.localStorage.getItem(SESSION_KEY);
    if (!sessionId) {
      queueMicrotask(() => setLoading(false));
      return;
    }
    getSession(sessionId)
      .then(setSession)
      .catch(() => window.localStorage.removeItem(SESSION_KEY))
      .finally(() => setLoading(false));
  }, []);

  async function begin() {
    setLoading(true);
    setError(null);
    try {
      const created = await startSession();
      window.localStorage.setItem(SESSION_KEY, created.session_id);
      setSession(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start RoomiCheck.");
    } finally {
      setLoading(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!session?.current_question || !answer.trim()) return;
    const question = session.current_question;
    const value: AnswerValue = {
      free_text: question.question_type === "free_text" ? answer.trim() : answer === "other" ? otherAnswer.trim() : null,
      scale_value: question.question_type === "scale" ? Number(answer) : null,
      selected_option_id: question.question_type === "single_choice" ? answer : null,
    };
    setLoading(true);
    setError(null);
    try {
      setSession(await submitAnswer(session.session_id, question.id, value));
      setAnswer("");
      setOtherAnswer("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save that response.");
    } finally {
      setLoading(false);
    }
  }

  async function restart() {
    if (!session) return;
    setLoading(true);
    try {
      const created = await restartSession(session.session_id);
      window.localStorage.setItem(SESSION_KEY, created.session_id);
      setSession(created);
      setAnswer("");
      setOtherAnswer("");
    } finally {
      setLoading(false);
    }
  }

  if (loading && !session) return <main><p>Loading RoomiCheck…</p></main>;

  if (!session) {
    return (
      <main>
        <section className="card hero">
          <p className="eyebrow">ROOMICHECK</p>
          <h1>Describe how home works best for you.</h1>
          <p>Answer a short adaptive questionnaire and receive an explainable co-living preference profile.</p>
          <button onClick={begin} disabled={loading}>Start questionnaire</button>
          {error && <p role="alert" className="error">{error}</p>}
        </section>
      </main>
    );
  }

  if (session.status === "complete") {
    return (
      <main>
        <section className="card">
          <p className="eyebrow">PROFILE COMPLETE</p>
          <h1>Your co-living profile</h1>
          <p>{session.final_summary}</p>
          <p className="note">Scores describe preferences, not whether someone is a good or bad roommate.</p>
          <button onClick={restart} disabled={loading}>Start over</button>
        </section>
      </main>
    );
  }

  const question = session.current_question;
  return (
    <main>
      <section className="card">
        <div className="progress-row">
          <span>Question {question?.order}</span>
          <span>{session.progress.answered} answered · up to {session.progress.maximum}</span>
        </div>
        <div className="progress"><span style={{ width: `${Math.min(100, (session.progress.answered / session.progress.target_maximum) * 100)}%` }} /></div>
        <form onSubmit={submit}>
          <h1>{question?.text}</h1>
          {question && ["free_text", "scenario"].includes(question.question_type) && (
            <textarea value={answer} onChange={(event) => setAnswer(event.target.value)} maxLength={4000} rows={7} autoFocus />
          )}
          {question?.question_type === "scale" && (
            <div className="choices">
              {[1, 2, 3, 4, 5].map((value) => (
                <label key={value}><input type="radio" name="answer" value={value} checked={answer === String(value)} onChange={(event) => setAnswer(event.target.value)} />{value}</label>
              ))}
            </div>
          )}
          {question?.question_type === "single_choice" && (
            <div className="choice-list">
              <p className="note">Choose the response that best describes how the situation would make you feel.</p>
              {question.options.map((option) => (
                <label key={option.id}><input type="radio" name="answer" value={option.id} checked={answer === option.id} onChange={(event) => setAnswer(event.target.value)} />{option.label}</label>
              ))}
              {answer === "other" && (
                <textarea aria-label="Describe your answer" placeholder="Describe your answer" value={otherAnswer} onChange={(event) => setOtherAnswer(event.target.value)} maxLength={4000} rows={4} autoFocus />
              )}
            </div>
          )}
          <button type="submit" disabled={loading || !answer.trim() || (answer === "other" && !otherAnswer.trim())}>{loading ? "Saving…" : "Continue"}</button>
          {error && <p role="alert" className="error">{error}</p>}
        </form>
      </section>
    </main>
  );
}
