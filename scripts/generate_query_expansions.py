"""Write hypothetical answer passages for evaluation questions, using a local Ollama model.

    python scripts/generate_query_expansions.py qwen2.5:7b expansions.json data/evaluation/*.json

Standard library only, so it runs on the host where Ollama listens. The prompt is the one in
app/rag/query_expansion.py (keep the two in sync). Results are cached by question text, so a
re-run only generates what is missing. Feed the output to evaluation.query_expansion_eval.
"""

import json
import sys
import time
import urllib.request

SYSTEM = (
    "You help search industrial maintenance and energy-efficiency documents. Given a question, "
    "write a short passage (two or three sentences) that could appear in a technical manual and "
    "would answer it. Use the specific technical terms such a manual would use. "
    "Output only the passage."
)


def generate(model: str, question: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "system": SYSTEM,
            "prompt": question,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 90},
        }
    ).encode()
    request = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body,
        headers={"content-type": "application/json"},
    )
    return json.load(urllib.request.urlopen(request, timeout=900))["response"].strip()


def main() -> None:
    model, out, files = sys.argv[1], sys.argv[2], sys.argv[3:]
    try:
        cache = json.load(open(out))
    except FileNotFoundError:
        cache = {}
    generate(model, "warm up")
    started, made = time.time(), 0
    for path in files:
        for item in json.load(open(path)):
            question = item["question"]
            if question not in cache:
                cache[question] = generate(model, question)
                made += 1
                json.dump(cache, open(out, "w"), indent=1)
    print(f"generated {made} expansions in {time.time() - started:.0f} s -> {out}")


if __name__ == "__main__":
    main()
