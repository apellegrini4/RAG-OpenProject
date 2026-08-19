""" Empties the sandbox project, deleting the work packages inside it.

    usage: python tools/reset_sandbox.py
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
API_KEY = os.getenv("OP_API_KEY")
OP_URL = os.getenv("OP_URL").rstrip("/")
API_V3 = f"{OP_URL}/api/v3"
AUTH = ("apikey", API_KEY)

SANDBOX_IDENTIFIER = "sandbox"


def list_sandbox_workpackages():
    url = f"{API_V3}/projects/{SANDBOX_IDENTIFIER}/work_packages"
    response = requests.get(url, auth=AUTH)
    response.raise_for_status()
    return response.json().get("_embedded", {}).get("elements", [])


def delete_workpackage(wp_id):
    url = f"{API_V3}/work_packages/{wp_id}"
    response = requests.delete(url, auth=AUTH)
    return response.status_code


def reset_sandbox(verbose=True):
    """cancella tutti i work package di SANDBOX"""
    items = list_sandbox_workpackages()
    if verbose:
        print(f"trovati {len(items)} work package in SANDBOX")

    deleted = 0
    for item in items:
        wp_id = item["id"]
        status = delete_workpackage(wp_id)
        ok = status in (202, 204)
        deleted += ok
        if verbose:
            esito = "ok" if ok else f"FALLITA (status {status})"
            print(f"  id {wp_id} ({item.get('subject')}): {esito}")

    return deleted, len(items)


if __name__ == "__main__":
    items = list_sandbox_workpackages()
    print(f"SANDBOX contiene {len(items)} work package:")
    for item in items:
        print(f"  id {item['id']}: {item.get('subject')}")

    confirm = input("\nCancellarli tutti? Scrivi 'si' per confermare: ").strip().lower()
    if confirm == "si":
        deleted, total = reset_sandbox()
        print(f"\n{deleted}/{total} cancellati.")
    else:
        print("cancelled, nothing deleted.")
