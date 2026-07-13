export type QuestionType = "free_text" | "scenario" | "scale" | "single_choice";

export interface Question {
  id: string;
  source_question_id: string;
  order: number;
  text: string;
  question_type: QuestionType;
  primary_dimension: string | null;
  options: Array<{ id: string; label: string }>;
  scale_min: number | null;
  scale_max: number | null;
}

export interface QuestionnaireSession {
  session_id: string;
  status: "active" | "processing" | "needs_retry" | "complete" | "abandoned";
  progress: {
    answered: number;
    minimum: number;
    target_minimum: number;
    target_maximum: number;
    maximum: number;
  };
  current_question: Question | null;
  final_profile: Record<string, unknown> | null;
  final_summary: string | null;
}

export interface AnswerValue {
  free_text: string | null;
  scale_value: number | null;
  selected_option_id: string | null;
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const REQUEST_TIMEOUT_MS = 90_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  init?.signal?.addEventListener("abort", abortFromCaller, { once: true });
  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new ApiError(response.status, payload?.detail ?? "RoomiCheck could not complete that request.");
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(408, "The request took too long. Please try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    init?.signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function startSession(): Promise<QuestionnaireSession> {
  return request("/questionnaire-sessions", { method: "POST", body: "{}" });
}

export function getSession(sessionId: string): Promise<QuestionnaireSession> {
  return request(`/questionnaire-sessions/${sessionId}`);
}

export function submitAnswer(sessionId: string, questionId: string, answer: AnswerValue): Promise<QuestionnaireSession> {
  return request(`/questionnaire-sessions/${sessionId}/answers`, {
    method: "POST",
    body: JSON.stringify({
      session_question_id: questionId,
      idempotency_key: crypto.randomUUID(),
      answer,
    }),
  });
}

export function restartSession(sessionId: string): Promise<QuestionnaireSession> {
  return request(`/questionnaire-sessions/${sessionId}/restart`, { method: "POST", body: "{}" });
}

export function retrySession(sessionId: string): Promise<QuestionnaireSession> {
  return request(`/questionnaire-sessions/${sessionId}/retry`, { method: "POST", body: "{}" });
}

export function recordQuestionDeployed(sessionId: string, questionId: string): Promise<void> {
  return request(`/questionnaire-sessions/${sessionId}/question-deployed`, {
    method: "POST",
    body: JSON.stringify({ session_question_id: questionId }),
  });
}
