# RoomiCheck

RoomiCheck is an AI-native co-living assessment prototype for university housing. It combines scenario-based questions, contextual AI follow-ups, privacy controls, and validated profile synthesis to describe how a student prefers to share a room.

The current milestone generates a five-dimension co-living profile. It does not rank or match roommates yet.

## What It Does

- Uses five versioned scenarios covering cleanliness, sleep and study habits, guests, boundaries, and conflict communication.
- Uses Gemini as the primary reasoning layer to interpret answers, decide when clarification is useful, generate follow-ups, and synthesize the final profile.
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
