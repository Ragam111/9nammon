"""Run the fixed eval set through the same model-calling code the API uses (retry, timeout, streaming).

Usage (one command each):
  python -m scripts.run_eval            # against the configured model (MODEL_BASE_URL in .env)
  python -m scripts.run_eval --fake     # against a built-in fake that replies with each case's reference
Options: --min-pass 0.8 (exit 1 below this pass rate), --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, load_settings  # noqa: E402
from app.errors import from_exception  # noqa: E402
from app.keystore import KeyStore  # noqa: E402
from app.model_client import StreamResult, iter_text, open_stream  # noqa: E402

CASES_FILE = Path(__file__).resolve().parent.parent / "evals" / "cases.json"


def load_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _has_thai(text: str) -> bool:
    return any("฀" <= ch <= "๿" for ch in text)


def score(text: str, checks: dict[str, Any]) -> list[str]:
    """Return the list of failed checks (empty means pass). Matching ignores case."""
    low = text.lower()
    failures: list[str] = []
    if not text.strip():
        return ["empty answer"]
    for needle in checks.get("contains_all", []):
        if needle.lower() not in low:
            failures.append(f"missing {needle!r}")
    any_of = checks.get("contains_any", [])
    if any_of and not any(n.lower() in low for n in any_of):
        failures.append(f"none of {any_of!r}")
    for needle in checks.get("must_not_contain", []):
        if needle.lower() in low:
            failures.append(f"must not contain {needle!r}")
    if checks.get("thai") and not _has_thai(text):
        failures.append("not Thai")
    if "max_chars" in checks and len(text) > checks["max_chars"]:
        failures.append(f"longer than {checks['max_chars']} chars ({len(text)})")
    return failures


def fake_transport(cases: list[dict[str, Any]]) -> httpx.MockTransport:
    """A model that streams each case's reference answer, so --fake checks the harness end to end."""
    answers = {c["prompt"]: c["reference"] for c in cases}

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][-1]["content"]
        text = answers.get(prompt, "")
        chunks = [text[i:i + 12] for i in range(0, len(text), 12)]
        body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks)
        body += f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


async def run_case(client: httpx.AsyncClient, settings: Settings, api_key: str, case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result = StreamResult()
    error = ""
    try:
        response = await open_stream(client, settings, api_key, case["prompt"])
        async for _ in iter_text(response, result, settings.max_output_tokens * 8):
            pass
    except Exception as exc:  # recorded as a failed case, never raised
        error = from_exception(exc).type
    failures = [f"error: {error}"] if error else score(result.text, case["checks"])
    return {"id": case["id"], "pass": not failures, "failures": failures,
            "latency_ms": int((time.perf_counter() - started) * 1000), "chars": len(result.text)}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = sorted(r["latency_ms"] for r in results) or [0]
    passed = sum(r["pass"] for r in results)
    return {"cases": len(results), "passed": passed, "pass_rate": round(passed / max(1, len(results)), 3),
            "latency_ms_p50": int(statistics.median(latencies)),
            "latency_ms_p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]}


async def run_all(settings: Settings, cases: list[dict[str, Any]], fake: bool) -> dict[str, Any]:
    transport = fake_transport(cases) if fake else None
    api_key = "fake" if fake else KeyStore(settings.model_api_key, settings.data_dir).get()
    timeout = httpx.Timeout(settings.model_timeout_s, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        results = [await run_case(client, settings, api_key, c) for c in cases]  # one at a time: low-RAM friendly
    return {"model": "fake" if fake else settings.model_name, "summary": summarize(results), "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixed eval set")
    parser.add_argument("--fake", action="store_true", help="use the built-in fake model (no network)")
    parser.add_argument("--min-pass", type=float, default=0.8, help="exit 1 if the pass rate is below this")
    parser.add_argument("--out", type=Path, help="also write the full report to this JSON file")
    args = parser.parse_args(argv)
    report = asyncio.run(run_all(load_settings(), load_cases(), args.fake))
    for r in report["results"]:
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['id']:<14} {r['latency_ms']:>6} ms  {'; '.join(r['failures'])}")
    print(json.dumps(report["summary"], ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["summary"]["pass_rate"] >= args.min_pass else 1


if __name__ == "__main__":
    sys.exit(main())
