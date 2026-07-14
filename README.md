# RoomiCheck

RoomiCheck is an AI-native co-living assessment prototype for university housing. It combines scenario-based questions, contextual AI follow-ups, privacy controls, and validated profile synthesis to describe how a student prefers to share a room.

The current milestone generates a six-dimension co-living profile. It asks targeted detail questions within each dimension before completing the profile. It does not rank or match roommates yet.

## What It Does

- Uses five versioned scenarios covering cleanliness, sleep and study habits, guests, boundaries, and conflict communication.
- Treats Gemini as an adaptive interviewer: it interprets answers, extracts evidence-backed traits, and words targeted follow-ups; deterministic backend code owns scoring, coverage, and completion.
- Returns structured 1-5 scores with confidence, evidence, preferences, explicit dealbreakers, and unresolved questions.
- Redacts common identifiers and withholds sensitive-topic responses before any AI request.
- Validates all AI dimensions, score ranges, confidence values, and output fields.
- Completes the questionnaire with deterministic scoring and curated follow-ups when Gemini is unavailable.
- Saves versioned JSON profiles locally and can capture anonymous accuracy feedback.

## Requirements

- Python 3.11
- `uv`
- A Gemini API key for live AI mode

No third-party Python runtime packages are required.

## Setup

Create `.env.local` from `.env.example` and set your key:

```env
GEMINI_API_KEY="your-key"
GEMINI_MODEL="gemini-3.5-flash"
```

Check connectivity and structured output:

```powershell
uv run .\scripts\test_gemini_api_key.py
```

## Run

Interactive AI-native assessment:

```powershell
uv run .\scripts\run_questionnaire.py --feedback
```

Prepared synthetic demonstration using Gemini when available:

```powershell
uv run .\scripts\run_demo.py
```

Guaranteed offline demonstration of the continuity path:

```powershell
uv run .\scripts\run_demo.py --offline
```

Show the complete generated JSON without saving it:

```powershell
uv run .\scripts\run_demo.py --offline --json --no-save
```

Profiles are saved under `data/profiles/`. Feedback is stored separately under `data/feedback/` and does not duplicate profile contents.

## Internal journey audit

The web questionnaire keeps only an opaque session ID in the browser. The
protected audit view retains and displays the full demo journey without
deleting any collected data.

Set a private token in `.env.local`:

```env
INTERNAL_AUDIT_TOKEN="a-long-random-private-token"
ABANDONMENT_TIMEOUT_MINUTES="30"
```

After starting the API and web app, open:

```text
http://localhost:3000/internal/sessions/<session-id>
```

Use the session ID from the browser's `roomicheck_session_id` local-storage
value and enter the configured audit token. The API route is disabled unless
the token is configured. Sessions that exceed the inactivity timeout are
marked abandoned for timeline purposes; questions, answers, snapshots, AI
runs, and events are retained.

## Test

```powershell
uv run python -m unittest discover -s tests -v
```

## Architecture

```text
questionnaire/             Versioned questions, scoring anchors, fallbacks
roomicheck/ai_provider.py  Gemini Interactions API and resilient routing
roomicheck/privacy.py      Identifier redaction and sensitive-topic controls
roomicheck/scoring.py      Deterministic anchors and profile synthesis
roomicheck/models.py       Validated domain and profile contracts
roomicheck/questionnaire.py Session orchestration
roomicheck/storage.py      Local profile and feedback persistence
roomicheck/cli.py          Interactive and demonstration interface
tests/                     Unit and end-to-end continuity tests
```

The implementation plan is in `docs/specs/co-living-profile-generator.md`. The meeting demonstration script is in `docs/demo-rundown.md`.

## Hybrid AI approach

RoomiCheck does not use the model as its scoring engine. A seed answer is
interpreted into a structured profile whose traits carry weights and confidence.
The backend identifies missing or low-confidence fields, deterministically
chooses the highest-priority information gap, and asks the model to select or
adapt an appropriate next question for that gap.

For free-text responses, the model applies defined rubrics and returns a
bounded interpretation, such as a preference label, confidence, and supporting
quote. Backend code validates that output, maps approved labels to numeric
values, and updates the stored profile state with deterministic math. The
canonical record is the structured profile and its evidence, not a raw chat
transcript.
