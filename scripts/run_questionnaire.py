import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILES = [ROOT_DIR / ".env.local", ROOT_DIR / ".env"]
DEFAULT_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

def load_env_files() -> None:
    for env_path in ENV_FILES:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value

def extract_output_text(response_payload: dict) -> str:
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    steps = response_payload.get("steps", [])
    collected = []
    for step in steps:
        content = step.get("content") or step.get("output", {}).get("content", [])
        for item in content:
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                collected.append(item["text"])
    return "\n".join(part.strip() for part in collected if part.strip()).strip()

def ask_gemini(system_prompt: str, user_prompt: str) -> str:
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_api_key:
        print("Error: GEMINI_API_KEY was not found in environment or .env.local")
        sys.exit(1)
        
    full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
    
    request_payload = {
        "model": DEFAULT_MODEL,
        "input": full_prompt,
        "generation_config": {
            "temperature": 0.7,
        },
    }
    
    request = urllib.request.Request(
        url=DEFAULT_URL,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "x-goog-api-key": gemini_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "RoomiCheck-Questionnaire/0.1",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as http_response:
            response_payload = json.loads(http_response.read().decode("utf-8"))
            return extract_output_text(response_payload)
    except urllib.error.HTTPError as error:
        print(f"Gemini API error: {error.code}")
        print(error.read().decode("utf-8", errors="replace"))
        sys.exit(1)
    except Exception as error:
        print(f"Error calling Gemini: {error}")
        sys.exit(1)

def score_free_text_with_ai(question_prompt: str, user_answer: str, dimensions: list) -> str:
    system_prompt = (
        "You are an expert roommate compatibility profiler. The user provided a free-text answer to a questionnaire. "
        f"Your task is to score and interpret their answer regarding the following dimensions: {', '.join(dimensions)}. "
        "Provide a concise, 1-2 sentence summary of their preference, boundary, or habit based ONLY on their answer. "
        "Do not include pleasantries. Just the interpretation."
    )
    user_prompt = f"Question: {question_prompt}\nAnswer: {user_answer}"
    return ask_gemini(system_prompt, user_prompt)

def run_questionnaire():
    load_env_files()
    seed_file = ROOT_DIR / "questionnaire" / "seed_questions.v1.json"
    
    if not seed_file.exists():
        print(f"Error: Could not find {seed_file}")
        sys.exit(1)
        
    with open(seed_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Use the first 5 questions
    questions = data.get("questions", [])[:5]
    
    profile = defaultdict(list)
    
    print("=== RoomiCheck Adaptive Questionnaire ===\n")
    print("You can answer each question by typing the number of an option, OR by typing your own free-text answer.\n")
    
    follow_up_system_instruction = (
        "You are an expert roommate compatibility profiler. I will give you a housing question and a student's answer. "
        "Your task is to ask exactly ONE insightful follow-up question to dive deeper into their habits, boundaries, or preferences. "
        "Ask about practical details (e.g. specific routines, how they handle a related situation, or what their boundaries are). "
        "Do not include any pleasantries or intro text. Just output the question itself directly."
    )
    
    for i, q in enumerate(questions, 1):
        target_dims = q.get("target_dimensions", ["general"])
        
        print(f"Q{i}: {q['prompt']}")
        for j, opt in enumerate(q['options'], 1):
            print(f"  {j}. {opt['label']}")
        
        user_input = input("\nYour answer (number or free text): ").strip()
        while not user_input:
            user_input = input("Please provide an answer: ").strip()
            
        selected_answer = ""
        is_free_text = False
        
        # Check if the user entered a valid number corresponding to an option
        if user_input.isdigit():
            choice = int(user_input)
            if 1 <= choice <= len(q['options']):
                selected_answer = q['options'][choice-1]['label']
                # Deterministic scoring: Fixed questions affect the profile directly
                for dim in target_dims:
                    profile[dim].append(f"[Fixed Choice] {selected_answer}")
            else:
                is_free_text = True
                selected_answer = user_input
        else:
            is_free_text = True
            selected_answer = user_input
            
        if is_free_text:
            print("\nInterpreting your free-text answer...")
            interpretation = score_free_text_with_ai(q['prompt'], selected_answer, target_dims)
            for dim in target_dims:
                profile[dim].append(f"[AI Scored] {interpretation}")
                
        # Now generate a follow-up question
        print("\nThinking of a follow-up...")
        context = f"Question: {q['prompt']}\nStudent's Answer: {selected_answer}"
        follow_up_q = ask_gemini(follow_up_system_instruction, context)
        
        print(f"Follow-up: {follow_up_q}")
        follow_up_ans = input("Your answer: ").strip()
        while not follow_up_ans:
            follow_up_ans = input("Please provide an answer: ").strip()
            
        print("\nScoring follow-up answer...")
        follow_up_interpretation = score_free_text_with_ai(follow_up_q, follow_up_ans, target_dims)
        for dim in target_dims:
            profile[dim].append(f"[AI Scored Follow-up] {follow_up_interpretation}")
            
        print("-" * 50 + "\n")
        
    print("=== Your RoomiCheck Profile ===\n")
    for dim, traits in profile.items():
        dim_name = dim.replace("_", " ").title()
        print(f"[{dim_name}]")
        for trait in traits:
            print(f" - {trait}")
        print()
        
    print("Thank you for completing the questionnaire!")

if __name__ == "__main__":
    try:
        run_questionnaire()
    except KeyboardInterrupt:
        print("\nQuestionnaire cancelled.")
