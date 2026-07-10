from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from roomicheck.ai_provider import GeminiProvider, ProviderError
from roomicheck.config import load_env_files


def main() -> int:
    load_env_files()
    provider = GeminiProvider()
    if not provider.available:
        print("Gemini check failed: GEMINI_API_KEY is not configured.")
        return 1
    try:
        result = provider.healthcheck()
    except ProviderError as error:
        print(f"Gemini check failed [{error.code}]: {error}")
        return 1
    print(f"Gemini structured output is ready ({provider.model}): {result['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

