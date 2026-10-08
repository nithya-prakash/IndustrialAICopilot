"""A fake OpenAI-compatible chat-completions server for load-testing the AI endpoints.

    FAKE_LATENCY_MS=400 FAKE_429_RATE=0.2 python loadtest/fake_llm_server.py     # port 9999

Why: a hosted free tier caps tokens per day, so a load test against it measures the quota, not
this application. This server answers deterministically (one manual search, then a valid cited
diagnosis), adds a configurable delay, and can reject a fraction of calls with 429 + Retry-After
so the retry and backoff behaviour is exercised. Point the app at it with LLM_PROVIDER=openai,
LLM_BASE_URL=http://host.docker.internal:9999/v1, LLM_MODEL=fake, LLM_API_KEY=x.
Results measure the application (HTTP, DB, retrieval, agent loop), NOT a real model's speed.
"""

import asyncio
import json
import os
import random
import re

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()
LATENCY = float(os.environ.get("FAKE_LATENCY_MS", "400")) / 1000
RATE_429 = float(os.environ.get("FAKE_429_RATE", "0"))
CITATION = re.compile(r"\[[^\[\]]+, p\.\d+\]")


def _diagnosis(citations: list[str]) -> str:
    cite = citations[:1]
    return json.dumps(
        {
            "summary": "Likely overheating from overload or restricted ventilation.",
            "visual_observations": [],
            "sensor_findings": [],
            "possible_causes": [
                {"cause": "Sustained overload", "rank": 1, "supporting_citations": cite},
                {"cause": "Blocked ventilation", "rank": 2, "supporting_citations": cite},
            ],
            "recommended_checks": ["Check load current", "Clean the cooling fins"],
            "recommended_action": "Lock out the motor, then inspect cooling and load.",
            "severity": "medium",
            "limitations": ["Scripted answer from the fake model server."],
        }
    )


def _completion(content: str | None = None, tool_calls: list | None = None) -> dict:
    message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    return {
        "id": "fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    if RATE_429 and random.random() < RATE_429:
        return JSONResponse(
            {"error": {"message": "fake rate limit, try again shortly", "type": "rate_limit"}},
            status_code=429,
            headers={"retry-after": "1"},
        )
    await asyncio.sleep(LATENCY * random.uniform(0.7, 1.3))
    body = await request.json()
    messages = body["messages"]
    system = next((m["content"] for m in messages if m["role"] == "system"), "") or ""
    text = " ".join(str(m.get("content") or "") for m in messages)
    citations = CITATION.findall(text)
    if "route a maintenance diagnosis" in system:
        return _completion('{"next": "synthesize"}')
    if "maintenance planner" in system:
        plan = {
            "recommended_action": "Lock out the motor and inspect.",
            "recommended_checks": ["Check load"],
            "urgency": "soon",
            "safety_notes": [],
        }
        return _completion(json.dumps(plan))
    has_tool_result = any(m["role"] == "tool" for m in messages)
    if body.get("tools") and not has_tool_result:
        call = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "search_technical_documents",
                "arguments": json.dumps({"query": "overheating"}),
            },
        }
        return _completion(tool_calls=[call])
    if "specialist" in system:
        return _completion("done")
    return _completion(_diagnosis(citations))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "9999")), log_level="warning")
