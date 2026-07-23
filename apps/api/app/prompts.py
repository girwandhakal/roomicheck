"""Versioned prompts for the independent Stage 2 operations."""

EXTRACT_PROMPT_VERSION = "extract_response.v3"
EXTRACT_PROMPT = (
    "Interpret only the supplied co-living answer in the context of the complete question, question type, "
    "target dimension, selected option, and scale metadata. Return exactly one preference label: very_low, low, "
    "moderate, high, or very_high. "
    "confidence as exactly one of low, moderate, or high; do not calculate a numeric confidence. Return an explicit "
    "weight from 0.2 to 1.0. Copy supporting_quote exactly from answer.normalized_text. Use only allowed dimensions. "
    "Never infer protected traits, health, identity, or roommate quality. Return contradiction_response_ids "
    "only when the current answer conflicts with supplied prior evidence. For every returned dimension, also return any "
    "supported subdimensions: actual_behavior (what the person reports doing, without claiming objective truth), "
    "personal_preference (what they want), importance (how strongly it matters), and flexibility (how willing they are "
    "to adapt). Use the same labels, confidence, weights, and grounded supporting quotes. Omit a subdimension when "
    "the answer does not provide evidence for it. Never state that a person is objectively truthful or untruthful."
)

ADAPT_PROMPT_VERSION = "adapt_question.v1"
ADAPT_PROMPT = (
    "Reword the supplied curated multiple-choice question for the selected target only. Preserve its meaning, "
    "answerability, and options. Ask one practical non-sensitive question and end with a question mark."
)

SUMMARY_PROMPT_VERSION = "summarize_profile.v4"
SUMMARY_PROMPT = (
    "Synthesize the complete validated co-living profile into one natural paragraph named ideal_roommate. "
    "Write as a warm, confident note directly to the participant using you and your. Explain the kind of "
    "roommate relationship and shared-home atmosphere in which they are likely to feel at ease, drawing on "
    "the strongest supported patterns, priorities, flexibility, and meaningful tensions in the profile. "
    "Make it read like an insightful human synthesis, not a report or a recap. Use varied sentence structure, "
    "natural transitions, and concrete everyday behaviors. Integrate related preferences into a few themes rather "
    "than naming every category. Do not mention the questionnaire, questions, answers, dimensions, subdimensions, "
    "scores, labels, evidence, hypotheses, or the analysis process. Do not repeat or lightly paraphrase any "
    "question text. Do not use bullet points, headings, parenthetical lists, or phrases such as 'based on your "
    "answers.' Do not make compatibility or roommate-quality judgments, diagnose, judge, infer protected traits, "
    "or add facts. Return only the paragraph text in ideal_roommate."
)

ADAPTIVE_BUNDLE_PROMPT_VERSION = "adaptive_hypothesis_bundle.v1"
ADAPTIVE_BUNDLE_PROMPT = (
    "Analyze the sanitized questionnaire context and produce two or three competing hypotheses about how the "
    "participant's current responses align with earlier responses and where they may conflict. For every hypothesis, "
    "generate exactly two or three neutral, completely new questions that distinguish the hypotheses or close the "
    "stated evidence gap. Questions should target multiple relevant dimensions when natural, declare one primary and "
    "zero or more secondary canonical dimensions, and target supported subdimensions. Use only the supplied canonical "
    "dimensions and subdimensions. Do not expose the hypotheses to the participant, infer protected traits, diagnose, "
    "judge, or return numeric scores. For single-choice questions provide two to five balanced options including an "
    "Other option. Keep question text under 280 characters."
)
