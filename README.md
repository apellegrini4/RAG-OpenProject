# OpenProject Assistant in Decentraland

A system that connects a Decentraland scene to an OpenProject instance through a FastAPI
middleware. Inside the scene, an NPC (the assistant) receives natural-language questions, turns
them into structured requests to OpenProject using language models running locally with
**Ollama**, and returns the answer in the NPC's speech bubble.

The system has two parts, normally run together on the same machine:

1. **Middleware** (this folder) — a Python FastAPI server that talks to OpenProject and to Ollama.
2. **Decentraland scene** — a separate Node/TypeScript project (`decenetraland-scene`), containing
   the NPC and the panel used to interact with it. It lives in its own Git repository, outside
   this folder.

Everything runs locally: no data leaves the machine running the middleware and Ollama, except for
the direct calls to the configured OpenProject instance (and, if you expose the middleware
publicly, see [Section 6](#6-exposing-the-middleware-publicly-ngrok)).

---

## 1. Requirements

| Component | Version | Notes |
|---|---|---|
| Python | 3.11 | for the middleware |
| Node.js | ≥ 16 (a recent LTS is recommended) | for the Decentraland scene |
| npm | ≥ 6 | bundled with Node.js |
| Ollama | installed and running | to run the models locally — [ollama.com](https://ollama.com) |
| OpenProject access | instance URL + a personal API key | see [Configuration](#3-configuration) |

### Required Ollama models

The system uses two models across two phases: one to extract the parameters of the question
(Phase 1), one to write the final natural-language answer (Phase 2). Download both before the
first run:

```bash
ollama pull qwen2.5-coder:1.5b
ollama pull gemma3:4b
```

Check they downloaded correctly with `ollama list`. (Other model names can be passed per-request
via the API — see [Section 5](#5-api-endpoints) — but these two are the defaults the Decentraland
scene uses and the only ones required for a normal run.)

---

## 2. Installing the middleware

From this folder:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
```

> On Windows, if `pip.exe` gets blocked by an application-control policy, use
> `python -m pip install ...` as above instead of calling `pip.exe` directly.

---

## 3. Configuration

Create a `.env` file in this folder (git-ignored, must be created manually on each machine):

```
OP_URL=https://<your-domain>.openproject.com/
OP_API_KEY=<personal api key>
```

Generate the API key in OpenProject: avatar (top right) → **My account** → **Access tokens** →
generate a new key (shown once — copy it immediately).

`.env` is the only file that necessarily needs to change to run the system on a different machine
or with a different OpenProject instance/account. Linking a Decentraland wallet to an OpenProject
account is a separate, self-service step done from inside the scene (see
[Section 4.3](#43-linking-an-openproject-account-once-per-person)) — it does not touch `.env`.

---

## 4. Running the system

### 4.1 Start the middleware (API)

Ollama must already be running (it usually starts on its own after installation; otherwise
`ollama serve`). Then, from this folder with the virtual environment active:

```bash
uvicorn api:app --reload
```

The server starts on `http://127.0.0.1:8000`. Check it's up by opening
`http://127.0.0.1:8000/docs` (FastAPI's automatic docs UI).

### 4.2 Start the Decentraland scene

First time only, from the scene folder:

```bash
npm install
```

Then, with the middleware already running:

```bash
npm start
```

This opens a browser preview of the scene. The assistant is the clickable NPC; clicking it opens
the dialogue panel.

### 4.3 Linking an OpenProject account (once per person)

The assistant identifies the user by Decentraland wallet. The first time a wallet is used, if it
isn't linked yet, the reply says so and an **"Open link page"** button appears — it opens a page
where the player pastes their OpenProject API key (see [Section 3](#3-configuration)). From then
on, questions from that wallet run with that account's OpenProject permissions. The key is stored
server-side only and never returns to the browser or the scene.

---

## 5. API endpoints

| Endpoint | Method | Used by | Purpose |
|---|---|---|---|
| `/ask` | POST | direct/manual calls | ask a question, passing `username`, `api_key`, `model_name_phase1`, `model_name_phase2` explicitly |
| `/ask_dcl` | POST | the Decentraland scene | ask a question from a `wallet`; the middleware resolves the OpenProject account itself |
| `/wallet_status` | GET | the scene | checks whether a wallet is already linked, before showing the question panel |
| `/link_wallet` | GET/POST | browser (manual/emergency path) | HTML form to paste an API key and link a wallet |
| `/link_dcl` | POST | the scene | same linking flow as `/link_wallet`, called from inside Decentraland |

---

## 6. Exposing the middleware publicly (ngrok)

A published (non-preview) Decentraland scene cannot reach `http://127.0.0.1:8000` — browser/client
security blocks calls to `localhost` from a published World. Local preview (`npm start`) has no
such restriction and always works with the local middleware.

To make the middleware reachable from a published scene, the tested approach is an **ngrok
tunnel**, run in a second terminal alongside `uvicorn`:

```bash
# terminal 1
uvicorn api:app --reload

# terminal 2
ngrok http --domain=<your-static-domain>.ngrok-free.dev 8000
```

This requires the ngrok CLI (`winget install ngrok.ngrok` on Windows, or see
[ngrok.com](https://ngrok.com)) authenticated once with `ngrok config add-authtoken <token>`, and
a free static domain from the ngrok dashboard. Once the tunnel is up, update `MIDDLEWARE_URL` in
the scene's `assistant.tsx` to the ngrok URL and redeploy the scene.

Notes:
- The machine running the tunnel must stay on and the tunnel active for the whole session — it's
  not a permanent deployment, just exposure while you keep it running.
- Ollama processes one request at a time, so concurrent questions from multiple players are
  queued, not parallel.
- The public URL is reachable by anyone who has it while the tunnel is active, not only players
  inside the scene.
- `run_public.py` / `pyngrok` (also present in this folder) was an earlier attempt at automating
  this with a single Python command; it's superseded by the two-terminal approach above and can be
  ignored.
- On Windows, Defender or Smart App Control may flag/block the downloaded `ngrok.exe` (or
  `torch/lib/shm.dll` during install) as an unrecognized binary — this is a common false positive.
  Choose "Allow" on the Windows Security notification, or check **Windows Security → Virus &
  threat protection → Protection history** if no prompt appeared.

---

## 7. Project structure (quick reference)

```
RAG-OpenProject/                # this folder — the middleware
├── api.py                      # FastAPI app — see Section 5 for endpoints
├── accounts.py                 # maps identities (seed accounts + self-linked wallets) to OpenProject accounts/keys
├── accounts_store.json         # dynamic wallet → account links (git-ignored)
├── permissions.py              # checks OpenProject permissions before every write action
├── structured_URL_generator.py # Phase 1 — extracts parameters/filters from the question
├── response_generator.py       # Phase 2 — generates the natural-language answer
├── json_pruning.py             # trims OpenProject data before passing it to the model
├── request_helpers.py          # HTTP calls to OpenProject
├── llm_builder.py               # builds the Ollama (ChatOllama) instances used by both phases
├── benchmark/                  # evaluation tooling and datasets (not needed for normal use)
├── tests/                      # automated tests
├── tools/                      # support/maintenance scripts
├── requirements.txt
└── .env                        # to be created — see Section 3

decenetraland-scene/            # separate repository (not inside this folder), owned by a
                                 # collaborator — always `git pull` before `npm run deploy` to
                                 # avoid overwriting their changes
├── scene.json
├── package.json                # npm scripts: start, build, deploy
└── src/
    ├── assistant.tsx           # assistant NPC: UI, calls to /ask_dcl and /wallet_status, MIDDLEWARE_URL
    └── ui.tsx                  # integrates the panel into the scene's UI tree
```

---

## 8. Troubleshooting

**"could not reach the assistant" in the scene panel** — in local preview, check `uvicorn` is
running and `http://127.0.0.1:8000/docs` responds locally. On a published scene, check the ngrok
tunnel is active and `MIDDLEWARE_URL` in `assistant.tsx` matches it (see Section 6).

**"this wallet is not linked to any OpenProject account yet"** — expected the first time a wallet
is used; use the "Open link page" button (Section 4.3).

**The model responds very slowly to the first question** — expected: the first call after
starting Ollama loads the model into memory; later questions are faster.

**Error on `npm start` / `npm install`** — check the Node.js version (`node -v`, ≥ 16) and rerun
`npm install` in the scene folder.

**Permission denied on an action that should be allowed** — permissions are read live from the
connected OpenProject instance, not from a middleware setting: check the user's actual permissions
on that project in OpenProject.

**"Failed to load il2cpp" when opening the Decentraland desktop client** — usually Windows 11's
Smart App Control blocking an unrecognized binary. Fix: Windows Security → App & browser control →
Smart App Control → Off, then restart.
