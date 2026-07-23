---
name: adaptive-question-generation
description: Generate adaptive, cross-dimension questionnaire rounds from current user responses by forming multiple alignment and conflict hypotheses, producing two to three AI-generated follow-up questions per hypothesis, and deriving evidence-backed dimension and subdimension scores. Use when designing or implementing dynamic interview flows, question generation, hypothesis-driven clarification, or scoring changes for RoomiCheck-style profiles.
---

# Adaptive Question Generation

Use this skill to turn the current questionnaire state into a bounded adaptive round. Keep the model responsible for semantic hypotheses and wording; keep persistence, authorization, arithmetic, completion, and safety checks deterministic in the application.

## Workflow

1. Build a sanitized context from the seed response and all prior answered questions. Include question IDs, exact prompts, selected option IDs/labels or normalized free text, timestamps/order, existing dimension and subdimension states, evidence references, confidence, unknowns, and unresolved contradictions. Do not send raw identifiers or protected/sensitive content.
2. Ask the model for multiple hypotheses, normally three and never fewer than two unless the evidence is genuinely too sparse. Each hypothesis must state the observed response evidence, dimensions and subdimensions it may support, alignment with earlier evidence, plausible conflict or alternative interpretation, discriminating evidence, bounded confidence, and priority.
3. For every retained hypothesis, generate exactly two or three concise questions. Make each question answerable without knowing the internal hypothesis, scenario-based or preference-based, and useful to at least two eligible dimensions whenever the context supports that. Avoid duplicate wording, leading assumptions, diagnosis, labels about the person, and questions whose only purpose is one narrow dimension.
4. Return strict structured data. Every generated question must have a stable temporary ID, text, type, options when applicable, primary dimension, zero or more secondary dimensions, target hypothesis ID, target subdimensions, rationale, and the evidence gap it tests. Keep generated options balanced and include an explicit -other- path when the UI supports it.
5. Validate before presenting: question count per hypothesis is 2-3; IDs are unique; target dimensions are canonical; primary dimension is not repeated as secondary; text and options meet length/type constraints; no question repeats an already answered question; and every question has a clear evidence gap. Reject or regenerate invalid output. Fall back to curated questions if generation fails.
6. After each answer, run extraction against the question-s declared target dimensions plus any additional dimensions justified by the answer. Require direct evidence, a short supporting quote, a bounded label, confidence, and subdimension values for `actual_behavior`, `personal_preference`, `importance`, and `flexibility` when supported. Record inferred effects separately from direct effects.
7. Score deterministically from validated extraction. Map approved labels to the existing numeric scale, combine multiple answer contributions with weights, preserve evidence links to response IDs, lower confidence when evidence conflicts, and mark `clarification_needed` or `uncertain` rather than inventing certainty. A generated question may contribute to multiple dimensions, but it must not silently contribute to unauthorized dimensions.
8. Recompute coverage and stop/continue using the controller-s thresholds and hard maximum. Do not mark a dimension or subdimension sufficient solely because it has a model hypothesis; require direct evidence and the configured confidence threshold. Keep hypotheses and discarded alternatives in the audit trail.

## Prompt contract

Separate the model calls or clearly separated stages:

- `hypothesize`: compare current answers with previous evidence and output multiple alignment/conflict hypotheses.
- `generate_questions`: generate 2-3 questions for each selected hypothesis using only the sanitized context and hypothesis IDs.
- `extract`: interpret one answer into dimension/subdimension evidence, including contradictions and unknowns.

Use versioned prompt names and structured output schemas. Include the questionnaire version, profile schema version, canonical dimension IDs, canonical subdimension IDs, and scoring labels in every request. Never allow a final profile blob to bypass backend validation.

## Question design rules

- Prefer one question that probes a shared situation across environment, routine, boundaries, household structure, communication, social interaction, cultural openness, or rule flexibility.
- Ask about behavior, preferred outcome, importance, and flexibility across the round; do not force all four into every question.
- Test the highest-value uncertainty or conflict first. Select a question because its answer can distinguish hypotheses, not merely because a dimension is unmentioned.
- Preserve user agency: use neutral wording, allow -it depends,- and provide an -other- response path.
- Keep text under the application-s question limit and options short enough for the existing UI.

## Failure handling and privacy

Treat malformed output, provider errors, unavailable AI, privacy rejection, and insufficient context as explicit states. Retry only transient provider failures; otherwise use a deterministic fallback and record the reason. Never expose internal hypotheses to the user unless the product explicitly chooses to do so. Do not use sensitive or identifying material to infer roommate compatibility traits.

## Required test coverage

Add tests for two-versus-three hypotheses; exactly 2-3 questions per hypothesis; cross-dimension targets; duplicate and unauthorized target rejection; contradiction lowering confidence; direct versus inferred evidence; provider timeout/malformed output fallback; deterministic scoring; replay/idempotency; and audit reconstruction of hypothesis - question - answer - score.
