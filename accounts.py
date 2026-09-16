"""
Maps an identity coming from the outside world to the OpenProject account it stands for and the credential to act as that account.

Two levels, split by secrecy:
  - the SECRETS (the API tokens) stay in .env, which is git-ignored;
  - everything written here is public information and is version-controlled together with the code

"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

ACCOUNTS_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts_store.json")


def _load_dynamic_store():
    if not os.path.exists(ACCOUNTS_STORE_PATH):
        return {}
    try:
        with open(ACCOUNTS_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_dynamic_store(store):
    with open(ACCOUNTS_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def register_wallet(wallet, op_user_id, op_login, api_key):
    """ persist a self-registered wallet -> OpenProject account link. Re-linking the same wallet
    overwrites the previous entry (e.g. the player rotated their API key). Returns the username
    (== the lowercased wallet) that the rest of the system will now recognise """
    wallet_key = wallet.strip().lower()
    store = _load_dynamic_store()
    store[wallet_key] = {"op_user_id": op_user_id, "op_login": op_login, "api_key": api_key}
    _save_dynamic_store(store)
    return wallet_key

#op_user_id: the numeric id OpenProject assigns to the account
#op_login:   the login OpenProject recognises
#wallet:     not used anymore, now is /link_wallet (api.py) + accounts_store.json that resolve wallet -> account
#            dynamically and take priority in username_for_wallet()
#key_env:    names of the environment variables holding the API token
ACCOUNTS = {
    "alba.pellegrini": {
        "op_user_id": 4,
        "op_login": "albapellegrini04+1@gmail.com",
        #"wallet": "None",
        "key_env": ("OP_API_KEY_ALBA", "OP_API_KEY"),
    },
    "giulia.bianchi": {
        "op_user_id": 5,
        "op_login": "albapellegrini04+giulia@gmail.com",
        #"wallet": None,
        "key_env": ("OP_API_KEY_GIULIA",),
    },
    "mario.rossi": {
        "op_user_id": 6,
        "op_login": "albapellegrini04+mario@gmail.com",
        #"wallet": None,
        "key_env": ("OP_API_KEY_MARIO",),
    },
}

def get_account(username):
    """the account row for an identity label, or None if the label is unknown. Checks the static
    seed accounts first, then a self-registered wallet from the dynamic store """
    account = ACCOUNTS.get(username)
    if account:
        return account
    entry = _load_dynamic_store().get(username)
    if entry:
        return {
            "op_user_id": entry["op_user_id"],
            "op_login": entry.get("op_login"),
            "wallet": username,
            "key_env": None,
        }
    return None


def api_key_for(username):
    """the API token of an identity. For a seed account, read from the environment, for a
    self-registered wallet, read from the dynamic store. None if the account is unknown or has
    no key available """
    account = ACCOUNTS.get(username)
    if account:
        for var in account["key_env"]:
            value = os.getenv(var)
            if value:
                return value
        return None
    entry = _load_dynamic_store().get(username)
    return entry["api_key"] if entry else None


def username_for_wallet(wallet):
    if not wallet:
        return None
    target = wallet.strip().lower()
    for username, account in ACCOUNTS.items():
        if account.get("wallet") and account["wallet"].strip().lower() == target:
            return username

    if target in _load_dynamic_store():
        return target
    return None


