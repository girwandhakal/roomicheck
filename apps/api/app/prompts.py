"""Versioned prompts for the independent Stage 2 operations."""

EXTRACT_PROMPT_VERSION = "extract_response.v2"
EXTRACT_PROMPT = (
    "Interpret only the supplied co-living answer in the context of the complete question, question type, "
    "target dimension, selected option, and scale metadata. Return exactly one preference label: very_low, low, "
    "moderate, high, or very_high. "
    "confidence as exactly one of low, moderate, or high; do not calculate a numeric confidence. Return an explicit "
    "weight from 0.2 to 1.0. Copy supporting_quote exactly from answer.normalized_text. Use only allowed dimensions. "
    "Never infer protected traits, health, identity, or roommate quality. Return contradiction_response_ids "
    "only when the current answer conflicts with supplied prior evidence."
)

ADAPT_PROMPT_VERSION = "adapt_question.v1"
ADAPT_PROMPT = (
    "Reword the supplied curated multiple-choice question for the selected target only. Preserve its meaning, "
    "answerability, and options. Ask one practical non-sensitive question and end with a question mark."
)

SUMMARY_PROMPT_VERSION = "summarize_profile.v3"
SUMMARY_PROMPT = (
    "Analyze the complete validated co-living profile and return one paragraph named ideal_roommate. "
    "Describe the kind of person who would feel most natural to live with this participant, using all "
    "available dimension summaries, labels, evidence, and uncertainty. Write directly to the participant "
    "using you and your. Use simple everyday English, short sentences, and concrete shared-home behaviors. "
    "Do not return connections, tradeoffs, suggestions, or an overall-summary field. Do not compare the "
    "person to a hypothetical roommate, make compatibility or roommate-quality judgments, diagnose, judge, "
    "infer protected traits, or add facts."
)
