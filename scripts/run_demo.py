from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from roomicheck.cli import main


if __name__ == "__main__":
    arguments = ["--demo", *sys.argv[1:]]
    raise SystemExit(main(arguments))

