""" 
usage, witch uvicorn active on 127.0.0.1:8000 and Ollama:
    python tools/ask.py tester2 "Which work packages assigned to Tester 5 are still New?"
    python tools/ask.py --list
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE = "http://127.0.0.1:8000"

store = json.load(open(ROOT / "accounts_store.json", encoding="utf-8"))

if len(sys.argv) < 2 or sys.argv[1] == "--list":
    print("account collegati:")
    for wallet, entry in store.items():
        print(f"  {entry.get('op_login')}   ({wallet})")
    sys.exit(0)

who, question = sys.argv[1], " ".join(sys.argv[2:])
wallet = next((w for w, v in store.items()
               if (v.get("op_login") or "").lower() == who.lower() or w.lower() == who.lower()), None)
if not wallet:
    sys.exit(f"'{who}' non e' fra gli account collegati. Vedi: python tools/ask.py --list")

print(f"come {who} ({wallet[:12]}...)")
print(f"> {question}")
started = time.perf_counter()
r = requests.post(f"{MIDDLEWARE}/ask_dcl", json={"wallet": wallet, "question": question}, timeout=300)
r.raise_for_status()
data = r.json()
print(f"< {data.get('answer')}")
print(f"\nFase 1 ha estratto: {json.dumps(data.get('phase1_extraction'), ensure_ascii=False)}")
print(f"tempi: {data.get('timings')}  totale {round(time.perf_counter() - started, 1)}s")
