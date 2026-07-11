"""Versioned prompts for the independent Stage 2 operations."""

EXTRACT_PROMPT_VERSION = "extract_response.v1"
EXTRACT_PROMPT = (
    "Interpret only the supplied co-living answer in the context of the complete question, question type, "
    "target dimension, selected option, and scale metadata. Return labels low, moderate, or high and an explicit "
    "weight from 0.2 to 1.0. Copy supporting_quote exactly from answer.normalized_text. Use only allowed dimensions. "
    "Never infer protected traits, health, identity, or roommate quality. Return contradiction_response_ids "
    "only when the current answer conflicts with supplied prior evidence."
)

ADAPT_PROMPT_VERSION = "adapt_question.v1"
ADAPT_PROMPT = (
    "Reword the supplied curated multiple-choice question for the selected target only. Preserve its meaning, "
    "answerability, and options. Ask one practical non-sensitive question and end with a question mark."
)

SUMMARY_PROMPT_VERSION = "summarize_profile.v1"
SUMMARY_PROMPT = (
    "Write a neutral concise co-living preference summary grounded only in the validated profile. "
    "Mention uncertainty when present; do not diagnose, judge, infer protected traits, or add facts."
)
