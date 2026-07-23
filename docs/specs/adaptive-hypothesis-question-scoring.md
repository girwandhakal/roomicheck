# Adaptive Hypothesis-Driven Question and Scoring Plan

Time-date-stamp: 2026-07-22 20:55 America/Chicago

## Objective

Change dimension and subdimension scoring from a mostly fixed question-bank flow to an adaptive interview. Start with one broad seed question. Use accumulated answers to create multiple internal hypotheses about alignment with earlier responses and possible conflicts. Generate two to three user-facing questions for each hypothesis. Questions must be reusable evidence for multiple dimensions and subdimensions. Score only from validated evidence and retain a complete audit trail.

## Current baseline

The v2 implementation already has eight canonical dimensions, four subdimensions per dimension, cross-dimension question metadata, structured AI extraction, evidence references, contradiction records, privacy filtering, a deterministic controller, and curated fallbacks. The current gaps are the single seed plus fixed required questions, fixed follow-up selection by primary dimension, and no first-class hypothesis/question bundle persisted between rounds.

## Proposed lifecycle

```text
seed answer
  → sanitize + snapshot context
  → hypothesis generation (2–3 alternatives)
  → hypothesis validation/ranking
  → 2–3 generated questions per retained hypothesis
  → question validation + presentation
  → answer + extraction across declared targets
  → deterministic dimension/subdimension aggregation
  → conflict/coverage recomputation
  → next adaptive round or completion
```

The initial round contains exactly one active seed question. Generated questions are session-scoped and versioned; they are not written into the global curated bank.

## Domain and persistence changes

Add versioned contracts for `Hypothesis`, `GeneratedQuestion`, and `QuestionAnswerEvidence`. Include round/session IDs, evidence response IDs, aligned and conflicting dimensions, target subdimensions, discriminating evidence gaps, confidence/priority, prompt/model versions, source, validation status, direct/inferred kind, bounded labels, numeric contributions, weights, quotes, and contradiction links. Add foreign keys to sessions and response/question rows, uniqueness for one accepted answer per presented question, and protected storage for raw model payloads.

Increment schema/profile versions and add a migration. Existing sessions remain replayable through a compatibility adapter that treats legacy bank questions as a pre-adaptive round.

## AI contracts and prompts

Add strict schemas and versioned prompts in `apps/api/app/ai.py` and `apps/api/app/prompts.py`:

1. Hypothesis output: 2–3 hypotheses with evidence IDs, aligned/conflicting dimensions, subdimensions, alternative explanation, discriminating gap, confidence, and priority.
2. Question-bundle output: hypotheses plus exactly 2–3 questions each. Every question declares one primary and zero or more secondary canonical dimensions, target subdimensions, and the hypothesis/gap it tests.
3. Extraction output: bounded labels and confidence for each supported dimension/subdimension, supporting quote, direct/inferred kind, unknowns, and contradiction response IDs.

The provider may choose semantic targets and wording, but not numeric scores, completion, database IDs, or unauthorized dimensions. Validate strict structured output and reject extra fields. Keep logically separate `hypothesize`, `generate_questions`, and `extract` stages in audit records; combine requests only if latency requires it. Retry transient failures, then use a deterministic fallback bundle.

## Question generation policy

Retain the highest-value hypotheses covering distinct uncertainties or conflicts. Generate two questions for a clear high-signal hypothesis and three when behavior, preferred outcome, and flexibility/importance evidence are all needed. Avoid near-duplicates.

Each question must be neutral, concrete, short, user-answerable without internal reasoning, able to distinguish hypotheses or fill a material gap, multi-dimensional when natural, and tolerant of context dependence and “other.” Do not rely on sensitive attributes or diagnose the user. Question metadata is the authorization boundary for scoring targets.

## Scoring model

Aggregate validated contributions per dimension and subdimension. Preserve approved label-to-score and confidence mappings. Compute a bounded weighted score from direct evidence; inferred evidence supports context but cannot alone make coverage sufficient. Store all inputs for replay.

When evidence points in opposite directions, create/update a contradiction with involved response IDs, reduce confidence, retain both evidence items, and set `clarification_needed`. Do not average away a major conflict. A dimension is `sufficient` only with direct evidence, score, confidence at least 0.70, no unresolved major contradiction, and no required clarification. Apply the same discipline to subdimensions; otherwise leave them null/partial.

## Service/controller flow

Refactor selection so the controller asks for a generated bundle after the seed and after a completed bundle when unresolved conflicts remain. Track round state and answered generated question IDs. Select the next question from the active bundle, not from `next_for_dimension`. Keep the hard maximum and completion threshold; make completion depend on sufficient coverage across all eight dimensions and relevant subdimensions.

Make answer submission idempotent: a retry for the same presented question returns the existing result, and a retried AI request cannot create a second active bundle. Capture confidence-before/after snapshots and selection reasons for every question.

## API/UI changes

Keep the existing question response shape compatible, adding optional round/hypothesis metadata only for internal audit or feature-gated clients. Reuse existing UI components for generated question types. Remove assumptions that all questions belong to one primary dimension. Base progress on answered questions and coverage, not fixed bank length. Never expose hypotheses by default.

## Privacy, safety, and operations

Run all context through the existing privacy guard before provider calls. Minimize retained raw text, redact identifiers, and preserve protected audit access. Record prompt/model versions, latency, provider, fallback reason, hypothesis count, question count, validation failures, and scoring inputs. Add per-round rate and token budgets.

## Testing and rollout

Unit test schema validation, target authorization, cardinality, duplicate detection, score aggregation, contradiction handling, and legacy migration. Add service tests for seed → hypotheses → bundle → answers → profile, fallback, idempotent retries, maximum completion, and audit reconstruction. Add property tests for unknown-dimension rejection and 0–100 scores.

Roll out behind a feature flag. Shadow-generate bundles for fixed-flow sessions, compare coverage and question counts, then enable gradually. Monitor completion rate, provider failure/fallback rate, average questions per sufficient dimension, contradiction frequency, and feedback. Keep the fixed bank as fallback until acceptance criteria are met.

## Acceptance criteria

- Exactly one seed question starts a new adaptive session.
- Each adaptive round records at least two hypotheses when enough evidence exists.
- Each retained hypothesis produces two or three validated AI-generated questions.
- Questions safely score multiple dimensions and supported subdimensions.
- Every score is reproducible from stored answer evidence and deterministic aggregation.
- Conflicting evidence lowers confidence and remains in protected audit data.
- Malformed/provider/privacy failures fall back without blocking the questionnaire.
- Legacy sessions and fixed questions remain readable and replayable.
- Tests cover contracts, lifecycle, safety, scoring, fallback, and idempotency.

## Implementation sequence

1. Add schema/profile versions, persistence models, and migration.
2. Add strict hypothesis, bundle, extraction, and prompt contracts.
3. Add sanitization, provider fallback, validation, and audit records.
4. Refactor controller/service round state and deterministic multi-target scoring.
5. Update API/UI rendering and feature flagging.
6. Add unit, integration, replay, and property tests.
7. Shadow-run, measure, tune ranking rules, and roll out gradually.
