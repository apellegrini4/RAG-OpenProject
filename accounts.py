"""
Maps an identity coming from the outside world to the OpenProject account it stands for and the credential to act as that account.

Two levels, split by secrecy:
  - the SECRETS (the API tokens) stay in .env, which is git-ignored;
  - everything here -- numeric ids, logins, wallet addresses -- is public information and is
    version-controlled together with the code """

import os

from dotenv import load_dotenv

load_dotenv()

#op_user_id: the numeric id OpenProject assigns to the account
#op_login:   the login OpenProject recognises
#wallet:     the Decentraland address of the player
#key_env:    names of the environment variables holding the API token
ACCOUNTS = {
    "alba.pellegrini": {
        "op_user_id": 4,
        "op_login": "albapellegrini04+1@gmail.com",
        "wallet": None,
        "key_env": ("OP_API_KEY_ALBA", "OP_API_KEY"),
    },
    "giulia.bianchi": {
        "op_user_id": 5,
        "op_login": "albapellegrini04+giulia@gmail.com",
        "wallet": None,
        "key_env": ("OP_API_KEY_GIULIA",),
    },
    "mario.rossi": {
        "op_user_id": 6,
        "op_login": "albapellegrini04+mario@gmail.com",
        "wallet": None,
        "key_env": ("OP_API_KEY_MARIO",),
    },
}

#the projects of the instance, resolved once, this is a shortcut for tests and for readable messages, not a replacement
PROJECT_IDS = {
    "demo project": 1,
    "scrum project": 2,
    "sandbox": 3,
    "mobile app": 4,
    "data migration": 5,
    "website migration": 6,
    "internal audit": 7,
}


def get_account(username):
    """the account row for an identity label, or None if the label is unknown """
    return ACCOUNTS.get(username)


def api_key_for(username):
    """the API token of an identity, read from the environment. None if the account is unknown or its variable is not set """
    account = ACCOUNTS.get(username)
    if not account:
        return None
    for var in account["key_env"]:
        value = os.getenv(var)
        if value:
            return value
    return None


def username_for_wallet(wallet):
    if not wallet:
        return None
    target = wallet.strip().lower()
    for username, account in ACCOUNTS.items():
        if account.get("wallet") and account["wallet"].strip().lower() == target:
            return username
    return None


def project_id_for(project_name):
    """project name -> numeric id, case-insensitive. None if unknown to this table """
    if project_name is None:
        return None
    return PROJECT_IDS.get(str(project_name).strip().lower())
