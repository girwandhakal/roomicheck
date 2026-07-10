from __future__ import annotations

import re
from dataclasses import dataclass

from .models import PrivacyEvent


@dataclass(frozen=True)
class PrivacyResult:
    text: str
    events: list[PrivacyEvent]
    ai_allowed: bool


class PrivacyGuard:
    _redaction_patterns = (
        ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
        ("phone", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}(?!\d)")),
        ("student_id", re.compile(r"\b(?:student\s*id|cw?ID)\s*[:#-]?\s*[A-Z0-9-]{5,}\b", re.I)),
        ("url", re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)),
        (
            "street_address",
            re.compile(
                r"\b\d{1,6}\s+[A-Za-z0-9.' -]{2,40}\s(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct)\b\.?,?",
                re.I,
            ),
        ),
    )

    _sensitive_topics = {
        "medical_or_disability": re.compile(
            r"\b(?:diagnos(?:is|ed)|medical condition|disability|disabled|medication|therapy|therapist|mental health)\b",
            re.I,
        ),
        "religion": re.compile(r"\b(?:religion|religious|church|mosque|synagogue|temple|christian|muslim|jewish|hindu)\b", re.I),
        "race_or_ethnicity": re.compile(r"\b(?:race|racial|ethnicity|ethnic background)\b", re.I),
        "sexual_orientation_or_gender_identity": re.compile(
            r"\b(?:sexual orientation|gay|lesbian|bisexual|transgender|gender identity)\b",
            re.I,
        ),
        "citizenship_or_immigration": re.compile(r"\b(?:citizenship|immigration status|visa status|undocumented)\b", re.I),
    }

    _unsafe_question_patterns = (
        re.compile(r"\b(?:full name|email address|phone number|student id|home address|exact address)\b", re.I),
        *tuple(_sensitive_topics.values()),
    )

    def sanitize_answer(self, text: str) -> PrivacyResult:
        sanitized = text.strip()
        events: list[PrivacyEvent] = []
        for category, pattern in self._redaction_patterns:
            sanitized, count = pattern.subn(f"[REDACTED_{category.upper()}]", sanitized)
            if count:
                events.append(PrivacyEvent(category=category, action="redacted", count=count))

        sensitive_events = []
        for category, pattern in self._sensitive_topics.items():
            if pattern.search(sanitized):
                sensitive_events.append(PrivacyEvent(category=category, action="withheld_from_ai"))

        if sensitive_events:
            return PrivacyResult(
                text="[SENSITIVE_RESPONSE_WITHHELD]",
                events=events + sensitive_events,
                ai_allowed=False,
            )
        return PrivacyResult(text=sanitized, events=events, ai_allowed=True)

    def validate_generated_question(self, question: str) -> tuple[bool, str]:
        candidate = question.strip()
        if not candidate or len(candidate) > 280:
            return False, "Question was empty or too long"
        if not candidate.endswith("?"):
            return False, "Question must end with a question mark"
        if any(pattern.search(candidate) for pattern in self._unsafe_question_patterns):
            return False, "Question requested identifying or sensitive information"
        return True, ""

