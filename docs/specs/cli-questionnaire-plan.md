# RoomiCheck CLI Questionnaire Plan

## Purpose

This document narrows the current prototype scope to the questionnaire itself.
The immediate goal is not a student-facing web product. The immediate goal is a
CLI-first questionnaire that can be run locally, exercised end to end, and used
as the foundation for later AI-driven follow-up behavior.

This stage should answer one practical question:

> Can we define a stable, versioned roommate-compatibility questionnaire and
> collect valid responses without building the UI stack yet?

## Stage 0 Goals

Stage 0 must:

- Provide a runnable questionnaire through the command line
- Store the seed questionnaire in a versioned machine-readable file
- Enforce answer validation locally
- Persist session output to a local JSON file
- Capture optional explanation text where needed
- Produce a simple structured profile preview from seed answers
- Establish contracts that later web and API work can reuse

## Stage 0 Non-Goals

Stage 0 will not:

- Build a browser UI
- Require a backend or database
- Call OpenAI
- Generate adaptive AI follow-up questions
- Perform roommate matching
- Handle authentication or multi-user administration

## Deliverables

The Stage 0 implementation consists of:

- `questionnaire/seed_questions.v1.json`
- `scripts/run_questionnaire.py`
- `questionnaire/sample_answers.v1.json`

## CLI Interaction Model

The CLI runner should support two modes:

### Interactive mode

The user runs:

```powershell
python scripts/run_questionnaire.py
```

The runner:

1. Loads the questionnaire definition
2. Presents one question at a time
3. Validates the response before continuing
4. Saves the completed session to a JSON artifact
5. Prints a concise profile preview at the end

### Non-interactive mode

The user runs:

```powershell
python scripts/run_questionnaire.py --answers-file questionnaire/sample_answers.v1.json
```

This mode is intended for testing and repeatable verification.

## Questionnaire Contract

Each question definition must contain:

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

Supported `response_kind` values in Stage 0:

- `single_select`
- `multi_select`

The content in `seed_questions.v1.json` is the source of truth for the
questionnaire. The CLI runner must not hardcode the seed question copy.

## Session Output Contract

Each completed session JSON should contain:

```text
session_id
questionnaire_id
questionnaire_version
started_at
completed_at
responses
profile_preview
```

Each response should contain:

```text
question_id
response_kind
selected_option_ids
explanation
answered_at
```

## Profile Preview Contract

Stage 0 does not attempt full AI interpretation. It only creates a lightweight
deterministic profile preview from the seed answers so the questionnaire output
is immediately inspectable.

The preview should summarize:

- Cleanliness
- Sleep and noise
- Guests
- Privacy
- Communication
- Conflict handling
- Flexibility
- Explicit dealbreakers

This preview is diagnostic only. It is not a compatibility score and not a
final matching profile.

## Why CLI First

The CLI-first path is the fastest way to stabilize the most important contract:
the questionnaire itself. It lets us validate wording, option design,
dealbreaker handling, response storage, and output shape before spending time
on frontend and backend infrastructure.

It also keeps the next stage clean:

- The question JSON can be reused by an API service.
- The session JSON shape can map directly to database records later.
- The deterministic preview can become a baseline for later AI evaluations.

## Stage 1 Follow-On

Once the CLI questionnaire is accepted, the next implementation stage should
introduce:

1. A backend service that loads the same questionnaire definition
2. Persistent storage beyond local files
3. AI-generated adaptive follow-up questions
4. Evidence-grounded structured profile snapshots
5. Resume and reset flows exposed through an API

At that point, the current `prototype-roadmap.md` remains the broader system
roadmap, while this document serves as the narrower questionnaire-first
implementation plan.

## Acceptance Criteria

Stage 0 is complete when:

1. The questionnaire can be run locally from one command.
2. All ten seed questions are presented in order.
3. Invalid single-select and multi-select answers are rejected.
4. `none` remains mutually exclusive in the dealbreaker question.
5. Selecting `other` in the dealbreaker question requires explanation text.
6. A completed session artifact is written to disk.
7. The CLI prints a deterministic profile preview grounded in the responses.
8. The questionnaire content can be edited in JSON without changing Python code.
