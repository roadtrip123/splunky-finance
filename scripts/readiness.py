import json
import os
import urllib.request

url = os.environ.get("BANK_READINESS_URL", "http://127.0.0.1:8001/ready")
with urllib.request.urlopen(url, timeout=5) as response:
    result = json.load(response)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "ready" else 1)
