"""Check whether a model endpoint can actually drive this agent.

An endpoint that answers chat requests is not necessarily usable here: every scenario depends on
the model emitting a well-formed tool call, and some reasoning models return their text in
`reasoning_content` and leave `content` empty. Both failures look like a working endpoint from a
plain chat request, so this asks the questions that matter.

    python3 scripts/check_endpoint.py --base-url https://inference.sharonai.cloud/api/v1 \\
        --model shared-gpt-oss-120b --api-key tv-pat-...

The key is passed without any "Bearer " prefix; the client adds it. A config that gives you a
full header value such as "Bearer tv-pat-..." needs the prefix stripped first.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

TOOL = {
    "type": "function",
    "function": {
        "name": "calculate_spending",
        "description": "Calculate authoritative spending in AUD cents for a date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "category": {"type": "string"},
            },
            "required": ["start", "end"],
        },
    },
}


def call(base_url, api_key, model, tools, timeout):
    body = {
        "model": model,
        "max_tokens": 800,
        "messages": [
            {
                "role": "user",
                "content": "How much did I spend on restaurants between 2026-08-01 and 2026-09-01?",
            }
        ],
    }
    if tools:
        body["tools"] = [TOOL]
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, {"error": error.read().decode()[:400]}
    except Exception as error:  # noqa: BLE001 - report any transport failure plainly
        return 0, {"error": f"{type(error).__name__}: {error}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    if args.api_key.lower().startswith("bearer "):
        raise SystemExit('Strip the "Bearer " prefix: pass only the key itself.')

    print(f"{args.model} at {args.base_url}\n")
    failures = []

    status, body = call(args.base_url, args.api_key, args.model, tools=False, timeout=args.timeout)
    print(f"1. Responds to a chat request      HTTP {status}")
    if status != 200:
        print(f"   {json.dumps(body)[:300]}")
        raise SystemExit("\nEndpoint unreachable or rejected the key. Nothing else can be tested.")

    message = (body.get("choices") or [{}])[0].get("message") or {}
    content, reasoning = message.get("content") or "", message.get("reasoning_content") or ""
    print(f"2. Puts its answer in `content`    {'yes' if content.strip() else 'NO'}")
    if not content.strip():
        failures.append(
            "Answers arrive empty. The text is in `reasoning_content`, which this agent does not "
            "read, so customers would see a blank reply."
            + (f" Reasoning began: {reasoning[:80]!r}" if reasoning else "")
        )

    status, body = call(args.base_url, args.api_key, args.model, tools=True, timeout=args.timeout)
    message = (body.get("choices") or [{}])[0].get("message") or {}
    calls = message.get("tool_calls")
    print(f"3. Emits a tool call when offered  {'yes' if calls else 'NO'}")
    if calls:
        print(f"   called: {calls[0].get('function', {}).get('name')}")
    else:
        failures.append(
            "No tool call. Every scenario depends on the model calling a banking tool, so this "
            "endpoint cannot drive the demo until tool calling is enabled."
        )

    print()
    if failures:
        for note in failures:
            print(f"BLOCKED: {note}\n")
        sys.exit(1)
    print("Usable: the endpoint answers, fills `content`, and calls tools.")


if __name__ == "__main__":
    main()
