# 🏠 RoomiCheck

**RoomiCheck** is an AI-native matching prototype designed to help university housing providers create highly compatible roommate assignments. Instead of relying on superficial yes/no checkboxes, RoomiCheck uses scenario-based questioning, dynamic AI follow-ups, and behavioral analysis to understand how students actually live, communicate, and share space.

---

## 🎯 Project Philosophy

Unlike traditional housing systems that only consider logistics, RoomiCheck focuses on true behavioral compatibility:
- **Scenario-Based Seeds:** Students answer practical, real-world scenario questions (e.g., *How do you handle your roommate bringing unannounced guests while you study?*).
- **Dynamic Follow-ups:** The Gemini LLM generates contextual follow-up questions tailored to a student's specific answers to uncover nuances and personal boundaries.
- **Hybrid Scoring Engine:** The system combines deterministic scoring (from fixed multiple-choice answers) with AI-interpreted scores (from free-text and follow-up answers) to construct a highly accurate numeric compatibility profile.

For a detailed breakdown of the product goals and matching methodology, see [`docs/project-overview.md`](docs/project-overview.md).

---

## 🛠️ Technical Stack & Specifications

- **Language:** Python >= 3.11
- **Package Manager:** `uv` (Fast Python package and environment manager)
- **AI Integration:** Google Gemini API (`gemini-3.5-flash` via the `interactions` endpoint)
- **Architecture:** Local CLI prototype with zero external database dependencies.

### Directory Structure

```text
Roomicheck/
├── docs/
│   └── project-overview.md        # Comprehensive goals and matching philosophy
├── questionnaire/
│   └── seed_questions.v1.json     # The core scenario-based questions and IDs
├── scripts/
│   ├── run_questionnaire.py       # Main interactive CLI application
│   └── test_gemini_api_key.py     # Diagnostic tool to verify Gemini connectivity
├── .env.local                     # Local environment variables (API Keys)
├── pyproject.toml                 # Project metadata and requirements
└── uv.lock                        # Locked dependencies
```

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have Python 3.11+ and the `uv` package manager installed on your system.
If you don't have `uv` installed, you can install it via PowerShell:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Configure Environment Variables
RoomiCheck requires a Google Gemini API Key to run its adaptive AI follow-ups and profile generation. 
Create or edit a `.env.local` file in the root directory of the project:
```env
GEMINI_API_KEY="your_actual_api_key_here"
```

---

## 💻 Important Commands

### Run the Interactive Questionnaire
This is the core entry point of the application. It will launch the CLI interface, walk you through the 5 seed scenarios, dynamically generate 2 follow-ups via Gemini, and print out your compiled RoomiCheck profile.
```powershell
uv run .\scripts\run_questionnaire.py
```

### Test API Connectivity
If you are running into issues with the LLM or want to ensure your `.env.local` is configured correctly without going through the full questionnaire, you can run the diagnostic script:
```powershell
uv run .\scripts\test_gemini_api_key.py
```

---

## 🧠 How the Profile Generation Works

The current prototype outputs a comprehensive text profile representing the student's behavior across 5 core dimensions:
1. **Living & Cleanliness**
2. **Studying & Sleep Habits**
3. **Socializing & Guests**
4. **Sharing Space & Boundaries**
5. **Communication & Conflict Handling**

Behind the scenes, responses are mapped to a numeric vector distance calculation:
- **`[Fixed Choice]`**: Directly maps to hardcoded algorithmic weights (e.g. `strict_clean` = 5/5).
- **`[AI Scored]` / `[AI Scored Follow-up]`**: Free-text answers are passed to Gemini to calculate numeric ratings and extract contextual rules.
These multi-dimensional numeric scales calculate "friction" between two potential roommates, aiming to minimize friction and prevent matching students with explicit dealbreakers.
