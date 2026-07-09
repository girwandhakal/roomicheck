# RoomiCheck Product Goal

## Product Goal

RoomiCheck helps university housing providers create more compatible roommate assignments and improve student satisfaction by building an adaptive roommate-understanding engine. Instead of relying on a rigid questionnaire or a magical, self-training LLM, RoomiCheck uses LLM reasoning, structured memory, feedback loops, and match-outcome learning to get better over time.

The system collects free-text descriptions, scenario-based responses, and structured preference answers, then converts those responses into a compatibility profile. This profile represents how the student actually lives, communicates, studies, socializes, handles conflict, and shares space. 

Students complete a scenario-based questionnaire containing consistent seed questions and personalized AI follow-ups. Their answers form a structured profile of their stated living preferences, boundaries, communication tendencies, and dealbreakers. Roommate matching is then based on deeper behavioral compatibility rather than simple yes/no preferences.

RoomiCheck compares profiles within a preconfigured pool of eligible students using transparent, reproducible matching logic. While assignments are being formed, students see only that RoomiCheck is working to create a match. After matching is complete, each student receives:

- Their assigned roommate's approved contact information
- An explanation of the strongest compatibility factors
- Potential areas of friction
- Topics to discuss before move-in

The prototype tests whether this experience can support more informed roommate assignments, increase student satisfaction, and ultimately reduce conflict-related room changes.

In simple terms:

```text
The university provides the housing context.
RoomiCheck provides compatibility guidance.
```

## Problem

University housing systems already manage logistical and administrative constraints such as housing eligibility, residence hall options, room types, housing terms, and valid roommate pools. Those systems may not capture the expectations and boundaries that affect how two students experience living together.

RoomiCheck focuses on compatibility signals such as:

- Cleanliness expectations
- Sleep and noise preferences
- Guest boundaries
- Privacy needs
- Communication tendencies
- Conflict-management preferences
- Flexibility
- Explicit dealbreakers

Questionnaire responses are self-reported signals. They do not prove how a student will behave or guarantee that two students will live together successfully.

## Prototype Users

### Students

Students complete the questionnaire, wait for matching to finish, and receive their completed assignment and match guidance. They do not browse or rank potential roommates.

### Housing Provider

The housing provider supplies a preconfigured eligible pool and controls when matching begins. In a future production system, the provider may also support students who opt out, make direct assignments, override recommendations, or integrate RoomiCheck with existing housing systems.

Those administrative workflows and production integrations are outside the current prototype.

## Prototype Workflow

### 1. Load a Preconfigured Housing Pool

The prototype begins with synthetic or preconfigured student and housing data. The data establishes which students are eligible to be matched with one another.

### 2. Complete the Compatibility Questionnaire

Every student receives a consistent set of seed questions. These questions establish a comparable baseline across the matching pool.

RoomiCheck then uses AI-generated follow-up questions to explore incomplete, ambiguous, or especially important responses. The follow-up experience should feel personal while continuing to measure the same defined compatibility dimensions for every student.

### 3. Build a Structured Profile

Questionnaire responses are converted into a structured compatibility profile. The profile records normalized signals for each compatibility dimension, explicit dealbreakers, and the evidence used to derive those signals.

Students should be able to review their own profile before it is used for matching. Profile summaries must distinguish direct student responses from AI-generated interpretations.

### 4. Form Assignments

RoomiCheck first applies university-defined eligibility rules and explicit dealbreakers as hard constraints. It then calculates compatibility using documented, weighted profile dimensions.

Eligibility checks, dealbreaker enforcement, compatibility scoring, and final pairing are deterministic and reproducible. AI does not independently decide the compatibility score or final assignment.

### 5. Wait for Matching

Until the housing provider starts matching and the assignment is finalized, the student-facing experience displays:

> We are working to create a match.

The prototype does not expose candidate lists or other students' questionnaire data.

### 6. Explain the Completed Match

After matching, RoomiCheck uses the structured profiles and deterministic matching results to generate a student-friendly explanation, outlining shared preferences and areas for discussion without disclosing private answers.

## The Adaptive Learning Engine (Post-Match Vision)

While the prototype tests the initial compatibility profiling, the long-term vision for RoomiCheck is to create a feedback loop where the system learns from actual match outcomes. 

**The full adaptive cycle works like this:**
1. **Initial Input:** A student answers scenario questions.
2. **Hypothesis Extraction:** The AI extracts hypotheses (e.g., *Cleanliness: unclear; Noise tolerance: moderate; Conflict style: avoids confrontation*).
3. **Identify Gaps:** The AI identifies missing or uncertain areas.
4. **Adaptive Questioning:** The AI asks targeted follow-ups based on the gaps.
5. **Profile Construction:** The AI builds a structured compatibility profile.
6. **Matching:** Roommates are paired based on deterministic scoring of their profiles.
7. **Outcome Reporting:** After living together, users report whether the match worked and where friction occurred.
8. **Analysis:** The AI compares its initial predictions versus the actual living outcome.
9. **System Evolution:** The system updates its question strategy, scoring weights, and examples for future cases.

**Example of System Learning:**
If the system matches two people because both said they were "clean," but they later experience friction over dishes, the system learns that "clean" is too vague. The next time a student identifies as "clean", it adapts its strategy to ask: *"When dishes pile up, what timeline feels acceptable to you: same day, next morning, 2–3 days, or flexible depending on the week?"*

For RoomiCheck, the "brain" is not just a fixed chatbot, nor an instantly self-training LLM. It is the combination of LLM reasoning, a structured roommate profile, question-selection strategy, a feedback database, match-outcome analysis, human review, and scoring models. This creates an adaptive AI system that learns from structured feedback and improves its questioning and matching over time.

## Role of AI

AI may:
- Generate personalized follow-up questions
- Convert free-text answers into proposed structured profile signals
- Summarize a student's profile for that student to review
- Explain the documented reasons behind a completed match
- Generate tailored pre-move-in discussion prompts

AI must not:
- Override university eligibility constraints
- Ignore an explicit dealbreaker
- Independently determine compatibility scores or assignments
- Present inferred behavior as fact
- Reveal private responses or sensitive information

## Matching Principles

### Hard Constraints
Hard constraints determine whether a pairing is allowed. These include university eligibility rules and student preferences explicitly designated as dealbreakers.

### Weighted Preferences
Other compatibility dimensions are soft preferences. They influence the compatibility score but do not automatically exclude a pairing.

### Transparency and Reproducibility
Given the same eligible pool, confirmed profiles, weights, and constraints, the matching system must produce the same scores and assignments. Each explanation must be grounded in the factors actually used by the matching system.

## Success Measures

The prototype should evaluate:
- Questionnaire completion rate
- Student satisfaction with the questionnaire and completed assignment
- Perceived usefulness of the match explanation and discussion guide
- Whether deterministic results can be reproduced and explained

The long-term university outcome is a reduction in conflict-related room-change requests.

## Non-Goals

The current prototype will not:
- Integrate with a live university housing system or single sign-on
- Support a roommate marketplace or candidate browsing
- Replace the university's authority over housing assignments
- Predict student behavior or guarantee zero roommate conflict

## Future Configuration

A production version may add:
- Configurable housing pools, eligibility rules, and matching deadlines
- Student opt-out and random-assignment paths
- Administrator assignments and overrides
- Auditing, monitoring, and bias evaluation
- Outcome reporting based on satisfaction, disputes, and room changes
