# RoomiCheck Prototype Technical Roadmap

## 1. Purpose

This document defines the technical roadmap and implementation contract for the
RoomiCheck prototype.

The prototype will be delivered in stages. Stage 1 is the only stage currently
approved for implementation. It validates one complete single-user workflow:

1. A student starts or resumes a questionnaire.
2. The student answers a common set of seed questions.
3. AI asks adaptive follow-up questions.
4. AI converts the answers into an internal structured compatibility profile.
5. The student sees that the questionnaire is complete.
6. A developer can inspect the profile and the evidence behind it.

Stage 1 does not match the student with another person. Multi-user housing
pools, compatibility scoring, roommate assignment, and match explanations are
later stages.

## 2. Stage 1 Goals

Stage 1 must demonstrate that RoomiCheck can:

- Run as a functional frontend, backend, database, and AI system
- Establish a consistent compatibility baseline through preset questions
- Ask relevant follow-up questions based on an individual's prior answers
- Stop questioning when the required dimensions have enough evidence
- Produce a validated, evidence-grounded internal profile
- Persist and resume an unfinished questionnaire
- Recover safely from AI and network failures
- Expose enough diagnostic information to evaluate AI behavior
- Run locally through one documented startup workflow
- Run as a hosted preview after local acceptance

## 3. Stage 1 Non-Goals

Stage 1 will not:

- Match roommates
- Calculate compatibility between people
- Rank or display roommate candidates
- Display the generated profile to the student
- Allow the student to edit the generated profile
- Implement student authentication
- Integrate with a university system
- Use real student or university data
- Implement administrator assignment workflows
- Support random or opt-out assignment
- Claim to predict actual student behavior

The profile is an internal prototype artifact. It exists so later stages can
evaluate compatibility without having to redesign the questionnaire data.

## 4. Technology Decisions

### 4.1 Repository Structure

Use a monorepo with these primary directories:

```text
apps/
  web/                    Next.js frontend
  api/                    FastAPI backend
docs/
  goal.md
  specs/
    prototype-roadmap.md
docker-compose.yml
.env.example
README.md
```

The frontend and backend are independently runnable applications. PostgreSQL is
shared infrastructure, not embedded in either application.

### 4.2 Frontend

Use:

- Next.js with the App Router
- React and TypeScript
- Responsive, accessible form controls
- Server-rendered pages by default
- Client components only for interactive questionnaire state
- Native `fetch` through a small typed API client
- No global client-state library in Stage 1

The App Router is the current Next.js routing model for layouts, pages, Server
Components, and Client Components. See the
[Next.js App Router documentation](https://nextjs.org/docs/app).

### 4.3 Backend

Use:

- Python
- FastAPI
- Pydantic for request, response, domain, and AI-output validation
- SQLAlchemy for persistence
- Alembic for database migrations
- Psycopg as the PostgreSQL driver
- The official OpenAI Python SDK

Pydantic models are the source of truth for the HTTP API. FastAPI will expose
the generated OpenAPI schema and interactive API documentation. See the
[FastAPI request-body documentation](https://fastapi.tiangolo.com/tutorial/body/).

### 4.4 Database

Use PostgreSQL from the start. Do not use an in-memory database or SQLite for
application behavior.

Local PostgreSQL runs through Docker Compose. The hosted preview uses Railway
PostgreSQL.

### 4.5 AI Provider

Use the OpenAI Responses API with Structured Outputs.

Initial configuration:

```text
OPENAI_MODEL=gpt-5.4-mini
OPENAI_REASONING_EFFORT=low
OPENAI_STORE_RESPONSES=false
```

`gpt-5.4-mini` is the initial low-cost model. The model identifier must be an
environment setting rather than a constant spread through the application.
Current model guidance is documented in the
[OpenAI model catalog](https://developers.openai.com/api/docs/models).

Every model response must conform to a strict JSON schema. Do not extract
application state from unvalidated prose. See the
[OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

RoomiCheck stores the canonical questionnaire state in PostgreSQL and sends the
required context with each model request. It does not rely on an OpenAI
conversation object or `previous_response_id` as the authoritative state.

Set `store=false` on model requests. Persist only the application records
required for prototype evaluation.

### 4.6 Local and Hosted Environments

Local development is the first delivery target.

Docker Compose must run:

```text
web
api
postgres
```

The hosted preview will use:

```text
Frontend: Vercel
Backend: Railway
Database: Railway PostgreSQL
```

Cloud deployment begins only after all local Stage 1 acceptance criteria pass.

## 5. User Experience

### 5.1 Student Routes

The frontend provides:

```text
/                       Welcome, disclosure, start, or resume
/questionnaire          Active questionnaire
/complete               Completion confirmation
```

### 5.2 Developer Route

The frontend also provides:

```text
/debug                   Protected prototype inspection
```

The debug page is not linked from the student experience. It requires a
server-configured debug credential and must not expose that credential to
browser JavaScript.

### 5.3 Student Flow

#### Welcome

The welcome page explains:

- The prototype asks about roommate-living preferences.
- Responses are self-reported and do not predict behavior.
- AI will ask follow-up questions.
- The prototype stores responses and AI interpretations for evaluation.
- The prototype does not perform roommate matching in Stage 1.

The primary action starts a new questionnaire or resumes the active session
identified in browser storage.

#### Seed Questions

The student answers ten preset questions. Each question supports one of:

- Single-select with an optional written explanation
- Multi-select with an optional written explanation
- Free text

The UI displays:

```text
Question N of up to 30
```

Do not imply that every student will receive 30 questions.

#### Adaptive Questions

After all ten seed questions are answered, the backend generates one adaptive
question at a time. The next question may be single-select, multi-select, or
free text.

The UI displays an explicit processing state while the backend evaluates the
answer and generates the next step. Submission controls remain disabled until
that request finishes.

#### Completion

When the backend completes the profile, the frontend navigates to the
completion page.

The completion page confirms that:

- The questionnaire is complete.
- The responses were saved.
- No roommate match has been created yet.

The profile is not displayed.

#### Resume

The browser stores an opaque session identifier. Returning to the application
loads the current server state and continues from the next unanswered
question.

#### Reset

The student may reset the prototype after confirming the action. Resetting:

1. Marks the current session as `abandoned`.
2. Preserves its responses and AI audit records.
3. Creates a new session with the current questionnaire version.
4. Replaces the browser's active session identifier.

## 6. Questionnaire Definition

### 6.1 Compatibility Dimensions

Stage 1 covers these eight areas:

```text
cleanliness
sleep_and_noise
guests
privacy
communication
conflict_handling
flexibility
dealbreakers
```

The first seven are profile dimensions. Dealbreakers are explicit constraints
stored separately.

### 6.2 Seed Questions

Store seed questions in a versioned backend data file such as:

```text
apps/api/app/questionnaire/seed_questions.v1.json
```

Validate the file at application startup. A session records the questionnaire
version and stores a copy of every presented question so historical sessions
remain interpretable after content changes.

The ten seed questions must cover:

| ID | Topic | Primary dimensions |
| --- | --- | --- |
| `seed_01` | Acceptable room condition during a busy week | cleanliness, flexibility |
| `seed_02` | Preferred weekday sleep and wake routine | sleep_and_noise |
| `seed_03` | Reaction to light or noise during sleep hours | sleep_and_noise, communication |
| `seed_04` | Expectations for daytime and evening guests | guests |
| `seed_05` | Expectations for overnight guests and notice | guests, privacy |
| `seed_06` | Sharing food, belongings, and room resources | privacy |
| `seed_07` | Raising a small recurring roommate concern | communication |
| `seed_08` | Responding to a disagreement or boundary violation | conflict_handling |
| `seed_09` | Compromising when routines conflict | flexibility, conflict_handling |
| `seed_10` | Explicit roommate dealbreakers | dealbreakers |

Use the following initial content. Option IDs are stable API values; labels may
receive copy edits only when the questionnaire version is incremented.

#### `seed_01`: Shared-room condition

Prompt:

> After a busy week, which description is closest to the condition you would
> find acceptable in a shared room?

Single-select options:

```text
very_relaxed       Personal items and unfinished cleanup can remain for several days.
relaxed            Some visible clutter is fine if shared paths and surfaces remain usable.
moderate           Temporary mess is fine, but I prefer regular cleanup.
orderly            I prefer the room to be clean and organized most days.
very_orderly       I am most comfortable when the shared room stays consistently tidy.
```

Allow an optional explanation.

#### `seed_02`: Sleep routine

Prompt:

> Which weekday sleep routine is closest to yours during a typical school
> term?

Single-select options:

```text
early              Usually asleep before 11 PM and awake before 7 AM.
standard           Usually asleep from 11 PM to 1 AM and awake from 7 AM to 9 AM.
late               Usually asleep after 1 AM and awake after 9 AM.
variable           My sleep and wake times change substantially from day to day.
schedule_dependent My routine depends on work, athletics, or another fixed commitment.
```

Allow an optional explanation for exact times or schedule constraints.

#### `seed_03`: Sleep environment

Prompt:

> When you are trying to sleep, how sensitive are you to a roommate's light
> and normal activity?

Single-select options:

```text
low                Normal light and quiet activity rarely bother me.
moderate_low       I notice them but can usually sleep.
moderate           I can tolerate brief activity but prefer it to stop soon.
moderate_high      I need low light and very quiet activity.
high               I need the room as dark and quiet as reasonably possible.
```

Allow an optional explanation.

#### `seed_04`: Guest frequency

Prompt:

> How often would you be comfortable with your roommate inviting guests into
> the room when you are also there?

Single-select options:

```text
rarely             Rarely or only for a specific reason.
monthly            A few times per month.
weekly             About once or twice per week.
frequent           Several times per week.
context_dependent  It depends more on timing and notice than frequency.
```

Allow an optional explanation.

#### `seed_05`: Overnight guests

Prompt:

> Which expectation is closest to yours for overnight guests?

Single-select options:

```text
not_comfortable    I am not comfortable with overnight guests in the room.
rare_agreement     Only rarely and after both roommates explicitly agree.
occasional_notice  Occasionally, with meaningful advance notice.
regular_notice     Regularly can be acceptable with meaningful advance notice.
case_by_case       I want roommates to decide each request together.
```

Allow an optional explanation.

#### `seed_06`: Sharing and borrowing

Prompt:

> Which approach to food, belongings, and room supplies would make you most
> comfortable?

Single-select options:

```text
separate           Keep belongings separate unless permission is given each time.
mostly_separate    Keep personal belongings separate but share agreed room supplies.
some_shared        Agree in advance on specific food, supplies, or belongings to share.
generally_shared   Share common items unless one roommate marks something as private.
flexible           Decide informally based on the item and situation.
```

Allow an optional explanation.

#### `seed_07`: Raising a recurring concern

Prompt:

> A small roommate habit has bothered you several times. What are you most
> likely to do first?

Single-select options:

```text
address_promptly   Bring it up directly and respectfully soon.
wait_then_address  Wait to see whether it continues, then discuss it directly.
informal_hint      Mention it casually before starting a serious conversation.
planned_talk       Ask to set aside a specific time to discuss it.
avoid_initially    Try to adapt or avoid raising it unless it becomes more serious.
```

Allow an optional explanation.

#### `seed_08`: Boundary violation

Prompt:

> Your roommate crosses a boundary you had already discussed. What response is
> closest to yours?

Single-select options:

```text
immediate_discussion  Discuss it as soon as possible.
cool_off_then_talk    Take time to cool off, then discuss it privately.
written_then_talk     Send a message first, then discuss it if needed.
seek_mediation        Attempt a direct discussion, then seek help if it is unresolved.
context_dependent     My response depends on the boundary and urgency.
```

Allow an optional explanation.

#### `seed_09`: Conflicting routines

Prompt:

> You and your roommate prefer routines that cannot both happen exactly as
> planned. Which approach is closest to yours?

Single-select options:

```text
alternate          Alternate which person's preference takes priority.
find_middle        Agree on a consistent middle-ground routine.
protect_priorities Identify each person's highest-priority needs and adapt the rest.
flex_day_to_day    Decide based on each day's circumstances.
seek_external_help Try to compromise, then ask a resident advisor for help if needed.
```

Allow an optional explanation.

#### `seed_10`: Explicit dealbreakers

Prompt:

> Which situations, if any, would make a roommate pairing unacceptable to you?
> Select only items that are true dealbreakers rather than general preferences.

Multi-select options:

```text
none
smoking_or_vaping_in_room
overnight_guests
frequent_guests
incompatible_sleep_or_quiet_hours
repeated_shared_space_mess
borrowing_without_permission
substance_use_in_room
other
```

`none` is mutually exclusive with every other option. Selecting `other`
requires free text. Any selected dealbreaker must be treated as explicit
student confirmation.

Each seed definition contains:

```text
id
version
prompt
response_kind
options
optional_explanation_prompt
target_dimensions
required
```

Question wording and options must avoid requesting protected characteristics or
presenting moral judgments as compatibility traits.

### 6.3 Adaptive Question Rules

An adaptive question must:

- Address one or two identified dimensions
- Be grounded in previous response IDs
- Resolve a specific ambiguity or missing signal
- Avoid repeating a previously answered question
- Avoid suggesting a preferred or socially desirable answer
- Avoid asking for protected or unnecessary sensitive information
- Use two to six options when structured
- Permit an optional explanation for structured responses
- Remain answerable without knowledge of another student's identity

The AI may propose only one next question per turn.

## 7. Profile Contract

### 7.1 Profile Shape

The internal profile is versioned JSON validated by Pydantic before storage.

```text
schema_version
status
dimensions
dealbreakers
overall_uncertainties
generated_at
```

Valid profile statuses are:

```text
in_progress
complete
incomplete
```

Each of the seven profile dimensions contains:

```text
dimension
normalized_values
summary
coverage
confidence
evidence_response_ids
uncertainties
```

`coverage` is one of:

```text
missing
partial
sufficient
```

`confidence` is a model-reported value from `0` through `1`. It is diagnostic
metadata, not a compatibility score and not sufficient by itself to complete a
dimension.

`evidence_response_ids` must reference responses from the current session.
Reject AI output containing an unknown response ID.

### 7.2 Dimension Values

The normalized values record preferences rather than personality diagnoses.
Unknown values are `null`; do not invent a neutral value. Integer fields use
the range `1` through `5` and the anchors below.

| Dimension | Field | Type and allowed values |
| --- | --- | --- |
| cleanliness | `desired_order` | Integer: 1 very relaxed, 3 moderate, 5 very orderly |
| cleanliness | `chore_consistency` | Integer: 1 as needed, 3 regular, 5 strongly scheduled |
| cleanliness | `mess_tolerance` | Integer: 1 very low, 3 moderate, 5 very high |
| sleep_and_noise | `typical_sleep_period` | `early`, `standard`, `late`, `variable`, `schedule_dependent` |
| sleep_and_noise | `sleep_sensitivity` | Integer: 1 low, 3 moderate, 5 high |
| sleep_and_noise | `noise_tolerance` | Integer: 1 very low, 3 moderate, 5 very high |
| sleep_and_noise | `quiet_hour_preference` | Object with nullable `start_time`, `end_time`, and `timezone` strings |
| guests | `guest_frequency_preference` | Integer: 1 rarely, 3 weekly, 5 very frequently |
| guests | `advance_notice_preference` | `none`, `same_day`, `one_day`, `multiple_days`, `case_by_case` |
| guests | `overnight_guest_stance` | `not_comfortable`, `rare_agreement`, `occasional_notice`, `regular_notice`, `case_by_case` |
| privacy | `sharing_stance` | `separate`, `mostly_separate`, `some_shared`, `generally_shared`, `flexible` |
| privacy | `borrowing_permission` | `ask_each_time`, `standing_permission`, `item_dependent` |
| privacy | `alone_time_need` | Integer: 1 low, 3 moderate, 5 high |
| communication | `directness_preference` | Integer: 1 indirect, 3 balanced, 5 very direct |
| communication | `communication_timing` | `immediate`, `after_cooling_off`, `scheduled`, `context_dependent` |
| communication | `communication_channel` | `in_person`, `text_first`, `either`, `context_dependent` |
| conflict_handling | `response_style` | `direct`, `reflect_then_discuss`, `written_first`, `mediated`, `context_dependent` |
| conflict_handling | `preferred_resolution_timing` | `immediate`, `same_day`, `within_few_days`, `context_dependent` |
| conflict_handling | `escalation_tolerance` | Integer: 1 avoid external help, 3 use after direct attempts, 5 seek help early |
| flexibility | `routine_adaptability` | Integer: 1 low, 3 moderate, 5 high |
| flexibility | `compromise_preference` | `alternate`, `middle_ground`, `protect_priorities`, `day_by_day`, `seek_mediation` |
| flexibility | `boundary_firmness` | Integer: 1 highly flexible, 3 context-dependent, 5 firm |

Intermediate integer values are valid. AI summaries must preserve the student's
context when a single normalized value cannot express an answer fully.

### 7.3 Dealbreakers

Each dealbreaker contains:

```text
category
student_description
explicitly_confirmed
evidence_response_id
```

The AI must not infer a dealbreaker. A dealbreaker is valid only when the
student explicitly selects or states it in a response.

## 8. Adaptive AI Orchestration

### 8.1 Seed Phase

During the seed phase:

1. The backend serves the next preset question.
2. The backend validates and stores the answer.
3. No adaptive question is requested until all ten seeds are complete.
4. After `seed_10`, the backend sends the seed transcript to the AI.
5. The AI produces the first full profile snapshot and either the first
   adaptive question or a completion recommendation.

Batching initial profile generation after the seed phase avoids an unnecessary
model call for each preset question.

### 8.2 Adaptive Phase

For every adaptive answer:

1. Validate the session, question, response shape, and idempotency key.
2. Store the response before calling OpenAI.
3. Build the AI input from the prompt version, profile schema, current full
   profile, and ordered session transcript.
4. Request a strict structured result.
5. Validate profile fields and evidence references.
6. Persist a new immutable profile snapshot.
7. Apply deterministic completion rules.
8. Store and return the next question, or finalize the session.

The AI result schema contains:

```text
profile
coverage_assessment
next_question
completion_recommendation
```

The AI recommends a next action, but backend code makes the final completion
decision.

### 8.3 Completion Rules

A session may finish before the hard cap only when:

- All ten seed questions have valid responses.
- Every profile dimension has `sufficient` coverage.
- Every dimension references at least two distinct responses.
- The dealbreaker question has an explicit response, including an explicit
  statement that there are no dealbreakers when applicable.
- No dimension contains an unresolved ambiguity marked as requiring a
  follow-up.
- The AI returns no next question and recommends completion.

The limits are:

```text
Seed questions: 10
Adaptive questions: 20 maximum
Total questions: 30 maximum
```

At 30 questions, the backend stops unconditionally. If any dimension is not
sufficient, the profile status becomes `incomplete`, and the affected
dimensions retain their missing or partial coverage.

### 8.4 Prompt Contract

Use a versioned system prompt. Its stable instructions appear before dynamic
session data to support prompt caching.

The prompt must instruct the model to:

- Treat responses as self-reported preferences
- Avoid diagnosing personality or predicting behavior
- Preserve uncertainty
- Ground every profile field in response evidence
- Ask only one relevant follow-up
- Never infer dealbreakers
- Never ask for protected characteristics
- Return only the required structured result

Store the prompt version with every AI run.

### 8.5 Failure Handling

Retry a model operation no more than twice for:

- Timeouts
- Rate limits
- Transient provider errors
- Invalid structured output
- Invalid evidence references

Use bounded exponential backoff.

If all attempts fail:

- Keep the student's answer.
- Keep the session in its current phase.
- Record the failed AI run and error category.
- Return a retryable service error.
- Let the frontend retry by replaying the same answer request with the same
  idempotency key.

An idempotency key ensures repeated requests cannot create duplicate responses,
questions, or profile snapshots.

If the model refuses a request, record the refusal and return a neutral
retryable error. Do not treat refusal text as profile data.

## 9. Persistence Model

### 9.1 `demo_users`

```text
id UUID primary key
created_at timestamp
```

Stage 1 creates demo identities without authentication. The table preserves a
future path to authenticated users.

### 9.2 `questionnaire_sessions`

```text
id UUID primary key
demo_user_id UUID
questionnaire_version string
profile_schema_version string
status enum
phase enum
seed_answer_count integer
adaptive_answer_count integer
current_question_id UUID nullable
created_at timestamp
updated_at timestamp
completed_at timestamp nullable
abandoned_at timestamp nullable
```

Session statuses:

```text
active
processing
complete
incomplete
abandoned
```

Session phases:

```text
seed
adaptive
finished
```

### 9.3 `session_questions`

```text
id UUID primary key
session_id UUID
source enum: seed | adaptive
source_definition_id string nullable
sequence_number integer
prompt text
response_kind enum
options JSONB
target_dimensions JSONB
grounding_response_ids JSONB
created_at timestamp
answered_at timestamp nullable
```

Enforce a unique `(session_id, sequence_number)` constraint.

### 9.4 `questionnaire_responses`

```text
id UUID primary key
session_id UUID
question_id UUID
selected_option_ids JSONB
free_text text nullable
idempotency_key string
created_at timestamp
```

Enforce unique constraints on `(session_id, question_id)` and
`(session_id, idempotency_key)`.

Limit free text to 2,000 characters in both frontend and backend validation.

### 9.5 `profile_snapshots`

```text
id UUID primary key
session_id UUID
version integer
profile JSONB
created_by_ai_run_id UUID
created_at timestamp
```

Profile snapshots are immutable. Enforce unique `(session_id, version)`.

### 9.6 `ai_runs`

```text
id UUID primary key
session_id UUID
trigger_response_id UUID nullable
operation enum
prompt_version string
model string
reasoning_effort string
attempt integer
status enum
provider_response_id string nullable
input_token_count integer nullable
output_token_count integer nullable
cached_token_count integer nullable
latency_ms integer nullable
error_category string nullable
validated_output JSONB nullable
created_at timestamp
completed_at timestamp nullable
```

Do not store API keys, authorization headers, or hidden model reasoning.

## 10. HTTP API Contract

All API routes use the `/api/v1` prefix and JSON request and response bodies.

### 10.1 Start a Session

```http
POST /api/v1/questionnaire-sessions
```

Request:

```json
{
  "resume_session_id": "optional UUID"
}
```

Behavior:

- Return the active session when the supplied ID is resumable.
- Otherwise create a demo user and a new questionnaire session.
- Create the first seed question instance when creating a session.

Response:

```json
{
  "session_id": "UUID",
  "status": "active",
  "phase": "seed",
  "progress": {
    "answered": 0,
    "maximum": 30
  },
  "current_question": {}
}
```

### 10.2 Get Session State

```http
GET /api/v1/questionnaire-sessions/{session_id}
```

Return the current public state, progress, and unanswered question. Do not
return the profile, AI trace, or prior free-text responses through this route.

Return `404` for an unknown session and `410` for an abandoned session.

### 10.3 Submit an Answer

```http
POST /api/v1/questionnaire-sessions/{session_id}/answers
```

Request:

```json
{
  "question_id": "UUID",
  "idempotency_key": "client-generated UUID",
  "selected_option_ids": [],
  "free_text": "optional text"
}
```

Response:

```json
{
  "session_id": "UUID",
  "status": "active | complete | incomplete",
  "phase": "seed | adaptive | finished",
  "progress": {
    "answered": 11,
    "maximum": 30
  },
  "current_question": {},
  "retry_required": false
}
```

`current_question` is `null` when finished.

Return:

- `400` for malformed answer content
- `404` for an unknown session or question
- `409` when answering a question that is not current
- `422` for a response that does not satisfy the question definition
- `503` when persisted input awaits retryable AI processing

Replaying the same idempotency key returns the prior successful result.
When the original request stored the response but exhausted AI retries,
replaying that key resumes AI processing against the stored response rather
than inserting another response.

### 10.4 Reset a Session

```http
POST /api/v1/questionnaire-sessions/{session_id}/reset
```

Return the new session using the same public shape as session creation.

### 10.5 Health

```http
GET /api/v1/health
```

Return application status and database connectivity. Do not call OpenAI from
the basic health endpoint.

### 10.6 Internal Inspection

```http
GET /api/v1/internal/questionnaire-sessions/{session_id}
```

Require an `X-Debug-Key` header. Return:

- Full session state
- Presented questions and responses
- All profile snapshots
- Dimension coverage and evidence references
- AI run metadata and errors
- Prompt, questionnaire, profile-schema, and model versions

The debug route is disabled when the required debug environment settings are
absent.

## 11. Security and Privacy Boundaries

Stage 1 uses synthetic prototype data, but it must preserve these boundaries:

- The OpenAI API key is available only to the backend.
- The debug credential is available only to backend and server-side frontend
  code.
- CORS uses explicit allowed frontend origins rather than `*`.
- Logs exclude response text, API keys, and debug credentials by default.
- Public API responses never expose the internal profile or AI trace.
- Free-text input is length-limited and rendered as escaped text.
- Database URLs and service credentials come from environment variables.
- Hosted environments use HTTPS.

FastAPI's CORS configuration should follow its
[CORS middleware guidance](https://fastapi.tiangolo.com/tutorial/cors/).

Authentication, formal authorization, production data retention, FERPA review,
and university security review are deferred because Stage 1 is not a
production student system.

## 12. Observability

Emit structured application logs containing:

```text
request_id
session_id
route
status_code
duration_ms
ai_run_id
ai_operation
ai_attempt
ai_latency_ms
ai_error_category
```

Do not include student response content in standard logs.

Track these prototype metrics:

- Sessions started
- Seed phase completion rate
- Full questionnaire completion rate
- Questions answered per completed session
- Adaptive questions asked per completed session
- AI request success and retry rates
- AI latency
- Input, output, and cached token usage
- Complete versus incomplete profile counts
- Coverage rate per dimension

Stage 1 does not require a separate telemetry vendor. Structured logs, database
audit records, and the debug page are sufficient.

## 13. Testing Strategy

### 13.1 Backend Unit Tests

Test:

- Seed question validation
- Session state transitions
- Response-kind validation
- Duplicate and stale answer rejection
- Idempotent answer replay
- Profile schema validation
- Unknown evidence-response rejection
- Dealbreaker confirmation rules
- Coverage completion rules
- Early completion rejection
- The 20-adaptive and 30-total caps
- Finalization with incomplete dimensions
- AI retry classification and limits

### 13.2 Backend Integration Tests

Run against PostgreSQL and test:

- Start, resume, reset, and abandon flows
- Question and response persistence
- Immutable profile snapshot versions
- AI audit records
- Transaction rollback on invalid AI output
- Recovery after a stored answer and failed AI call
- Internal endpoint protection
- CORS configuration

### 13.3 AI Contract Tests

Mock OpenAI in the normal automated test suite. Fixtures must cover:

- Valid first profile after seed completion
- Relevant next question
- Completion recommendation
- Invalid evidence reference
- Malformed structured response
- Provider timeout
- Rate limit
- Refusal
- Repeated question proposal
- Unsupported profile field

Provide a separate opt-in live smoke test that runs only when
`OPENAI_API_KEY` is set.

### 13.4 AI Evaluation Set

Create at least ten synthetic personas with:

- Seed answers
- Expected profile signals
- Expected uncertainties
- Useful follow-up topics
- Forbidden inferences
- Explicit dealbreaker expectations

The evaluation reports:

- Profile schema validity
- Evidence grounding
- Dealbreaker precision
- Follow-up relevance
- Duplicate-question rate
- Dimension coverage
- Question count
- Completion status

Every stored profile claim must reference a valid response. Every stored
dealbreaker must have explicit evidence.

### 13.5 Frontend Tests

Use component tests for dynamic question controls and Playwright for:

- Start
- Single-select answer
- Multi-select answer
- Free-text answer
- Optional explanation
- AI processing state
- Refresh and resume
- Retry after AI failure
- Completion
- Reset
- Protected debug access
- Keyboard navigation
- Mobile viewport behavior

### 13.6 End-to-End Acceptance

Stage 1 is accepted locally when:

1. One documented command starts the frontend, backend, and PostgreSQL.
2. A user can start and complete the questionnaire.
3. The first ten questions are the configured seeds.
4. Subsequent questions are adaptive and grounded in prior answers.
5. No session exceeds 30 questions.
6. Refreshing resumes at the correct question.
7. Reset creates a new session without deleting the old audit record.
8. AI failures can be retried without duplicating an answer.
9. Completion produces a validated internal profile.
10. The protected debug page shows profile evidence and AI metadata.
11. Automated backend, frontend, and end-to-end tests pass.

The cloud preview is accepted only after the same workflow passes against
Vercel and Railway.

## 14. Stage 1 Delivery Plan

### Stage 1A: Foundation

Deliver:

- Monorepo scaffolding
- Next.js and FastAPI health checks
- PostgreSQL and initial migrations
- Docker Compose
- Environment templates
- Seed question definitions and validation
- Session, question, and response persistence
- Start, answer, resume, and reset APIs
- Student questionnaire UI using mocked adaptive responses

Exit criteria:

- The complete seed flow works without OpenAI.
- Persistence, resume, and reset tests pass.

### Stage 1B: Adaptive AI

Deliver:

- Versioned AI prompt
- Strict structured-output models
- OpenAI service integration
- Initial profile generation after the seed phase
- Adaptive question generation
- Deterministic coverage and stopping controller
- Profile snapshots
- AI audit records
- Retry and idempotency behavior

Exit criteria:

- A live model can complete the single-user workflow.
- AI contract tests and the live smoke test pass.

### Stage 1C: Evaluation and Local Acceptance

Deliver:

- Protected debug page
- Synthetic persona evaluation suite
- Structured logs and prototype metrics
- Accessibility and responsive UI pass
- Full Playwright workflow
- Local setup and troubleshooting documentation

Exit criteria:

- All local Stage 1 acceptance criteria pass.
- Evaluation results contain no ungrounded dealbreakers.
- Every profile statement references valid evidence.

### Stage 1D: Hosted Preview

Deliver:

- Vercel frontend deployment
- Railway API and PostgreSQL deployment
- Production-mode migrations
- Hosted environment configuration
- Explicit CORS and secret configuration
- Hosted smoke and end-to-end tests

Exit criteria:

- The hosted preview passes the same core flow as local development.
- No debug or OpenAI secret appears in browser-delivered code.

## 15. Later Roadmap

Later stages are directional and require separate specifications before
implementation.

### Stage 2: Multi-User Housing Pools

Add:

- Authenticated identities
- Multiple concurrent questionnaire sessions
- Questionnaire version assignment
- Preconfigured eligible housing pools
- Privacy and consent controls
- Administrative pool visibility

### Stage 3: Deterministic Matching

Add:

- Hard eligibility constraints
- Explicit dealbreaker enforcement
- Weighted compatibility dimensions
- Pairwise compatibility scoring
- Whole-pool pairing optimization
- Odd-pool and unmatched-student handling
- Reproducible matching audit records

### Stage 4: Match Delivery

Add:

- Provider-triggered matching runs
- Student waiting state
- Final roommate contact disclosure
- Grounded match explanations
- Potential friction areas
- Pre-move-in discussion guides
- Administrator assignment and override configuration

## 16. Definition of Done

Stage 1 is done when the locally reproducible and hosted systems both support a
complete single-user adaptive questionnaire, persist all required state,
produce an evidence-grounded internal profile, expose protected diagnostic
information, recover from expected failures, and pass the documented automated
and AI evaluation suites.

Completing Stage 1 does not imply that matching quality has been validated. It
establishes the questionnaire and profile foundation required to evaluate
matching in later stages.
