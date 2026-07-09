# RoomiCheck CLI Adaptive Questionnaire

## Purpose

This document describes the implemented CLI-based adaptive questionnaire flow.
It is the production-style single-user questionnaire loop without a web UI,
database, or API server.

## Runtime Contract

The CLI runner:

1. Loads the ten seed questions from `questionnaire/seed_questions.v1.json`
2. Collects or preloads the seed answers
3. Sends the full transcript to the selected provider using an OpenAI-compatible API
4. Receives a strict structured result containing:
   - The updated compatibility profile
   - Coverage assessment
   - At most one adaptive follow-up question
   - A completion recommendation
5. Validates the AI output locally
6. Either asks the next adaptive question or finalizes the profile
7. Writes a full session artifact to disk

## Dependencies

Runtime requirements:

- Python
- An API key for either OpenAI or Groq

Optional environment variables:

- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLM_BASE_URL`
- `OPENAI_MODEL`
- `OPENAI_REASONING_EFFORT`
- `GROQ_MODEL`
- `GROQ_API_KEY`
- `OPENAI_API_KEY`
- `LLM_CA_BUNDLE`
- `LLM_DISABLE_SSL_VERIFY`
- `LLM_LOG_LEVEL`
- `LLM_DEBUG_DUMP`
- `GROQ_MIN_REQUEST_INTERVAL_SECONDS`
- `GROQ_MAX_TOKENS`

Environment loading:

- The CLI automatically loads `.env.local` first, then `.env`, from the repo root
- Existing shell environment variables take precedence over file values

TLS behavior:

- By default, HTTPS certificates are verified normally
- `LLM_CA_BUNDLE` can point to a PEM bundle file if the Python runtime does not trust the provider certificate chain
- `LLM_DISABLE_SSL_VERIFY=1` disables certificate verification and should be treated as a temporary development-only fallback

Default model:

```text
openai/gpt-oss-20b when GROQ_API_KEY is set
gpt-5.5 otherwise
```

## AI Request Shape

The runner uses an OpenAI-compatible API transport with:

- Top-level `instructions`
- Manual transcript replay through `input`
- `text.format` with `type: json_schema`
- `store: false`

The local application remains the source of truth for questionnaire state. It
does not rely on `previous_response_id` or a persistent OpenAI conversation.

Provider behavior:

- If `GROQ_API_KEY` is present, the runner defaults to Groq using `https://api.groq.com/openai/v1`
- If `OPENAI_API_KEY` is present and `GROQ_API_KEY` is absent, the runner defaults to OpenAI using `https://api.openai.com/v1`
- `LLM_PROVIDER` can explicitly force `groq` or `openai`

Provider transport details:

- OpenAI path: `/responses`
- Groq path: `/chat/completions` with `response_format.type=json_object`

The Groq path is optimized for free-tier usage:

- Compact request payload
- JSON object mode instead of strict schema mode
- Local validation and retry logic
- Request pacing between Groq calls to reduce TPM-limit collisions

Logging and debug artifacts:

- The CLI writes request-attempt logs to stderr
- When debug dumping is enabled, request and response payloads are written under `artifacts/llm_debug/`
- `LLM_LOG_LEVEL` controls console verbosity
- `LLM_DEBUG_DUMP=0` disables request/response dump files
- Groq request logs include request byte size and pacing waits

## Profile Contract

The AI returns a versioned internal profile with:

```text
schema_version
status
dimensions
dealbreakers
overall_uncertainties
generated_at
```

Each dimension must include:

```text
dimension
normalized_values
summary
coverage
confidence
evidence_response_ids
uncertainties
```

The runner rejects any profile that:

- References unknown response ids
- Omits required dimensions
- Uses invalid enum values
- Uses invalid numeric ranges
- Includes unconfirmed dealbreakers

## Adaptive Question Rules

Each AI-generated follow-up question must:

- Target one or two dimensions
- Reference known grounding response ids
- Avoid repeating an earlier prompt
- Use one of:
  - `single_select`
  - `multi_select`
  - `free_text`
- Use two to six options when structured
- Remain neutral and answerable without sensitive or protected information

The CLI validates those rules before showing the question.

## Completion Rules

The runner completes only when all of the following are true:

- All ten seed questions were answered
- Every dimension has `sufficient` coverage
- Every dimension cites at least two distinct evidence responses
- The dealbreaker seed question was answered
- No dimension retains unresolved uncertainties
- The model recommends completion
- The model does not propose another question

Limits:

```text
Seed questions: 10
Adaptive questions: 20 maximum
Total questions: 30 maximum
```

If the total cap is reached first, the profile is finalized as `incomplete`.

## Output Artifact

Each completed run writes a JSON artifact containing:

```text
session_id
questionnaire_id
questionnaire_version
prompt_version
profile_schema_version
status
started_at
completed_at
questions
responses
seed_preview
final_profile
completion_reason
ai_runs
```

`ai_runs` includes retry attempts, status, latency, usage snapshots when
available, and validated outputs or error categories.

## Failure Handling

The runner retries each AI step up to three times for transient or invalid
structured-output failures. If all attempts fail, the run exits with a clear
error message.

Explicit startup failures are also surfaced for:

- Missing provider API key for the selected provider
- Invalid CA bundle path

## Commands

Interactive:

```powershell
python scripts/run_questionnaire.py
```

Seed answers preloaded:

```powershell
python scripts/run_questionnaire.py --answers-file questionnaire/sample_answers.v1.json
```

Groq free-tier example:

```powershell
.\.venv\bin\python.exe .\scripts\run_questionnaire.py
```
