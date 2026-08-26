# OpenProject Assistant in Decentraland

A system that connects a Decentraland scene to an OpenProject instance through a FastAPI
middleware. Inside the scene, an NPC (the assistant) receives natural-language questions, turns
them into structured requests to OpenProject using language models running locally with
**Ollama**, and returns the answer in the NPC's speech bubble.

The system is made of two parts that need to be running together, on the same machine:

1. **Middleware** (this folder) — a Python FastAPI server that talks to OpenProject and to
   Ollama.
2. **Decentraland scene** — a separate Node/TypeScript project, containing the NPC and the
   interface used to interact with it.

Everything runs locally: no data leaves the machine where the middleware and Ollama are running,
except for the direct calls to the configured OpenProject instance.

---

## 1. Requirements

| Component | Version | Notes |
|---|---|---|
| Python | 3.10 or 3.11 | for the middleware |
| Node.js | ≥ 16 (a recent LTS is recommended) | for the Decentraland scene |
| npm | ≥ 6 | bundled with Node.js |
| Ollama | installed and running | to run the models locally — [ollama.com](https://ollama.com) |
| OpenProject access | instance URL + a personal API key | see the Configuration section |

### Required Ollama models

The system uses two models across two distinct phases: one to extract the parameters of the
question (Phase 1), and one to write the final natural-language answer (Phase 2). These are the
only two models required, and they need to be downloaded before the first run:

```bash
ollama pull qwen2.5-coder:1.5b
ollama pull gemma3:4b
```

Check that they were downloaded correctly with:

```bash
ollama list
```

---

## 2. Installing the middleware

From the project folder:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3. Configuration

Create a `.env` file in the project root (it is git-ignored, so it must be created manually on
each machine) with the OpenProject instance URL and your API key:

```
OP_URL=https://<your-domain>.openproject.com/
OP_API_KEY=<personal api key>
```

The API key is generated from OpenProject: avatar in the top right → **My account** → **Access
tokens** → generate a new API key (it is shown only once, copy it right away).

The `.env` file needs to be adapted case by case, depending on the OpenProject instance and the
account being used: it is the only file that necessarily has to be changed to run the system on a
machine other than mine.

Linking your Decentraland wallet to your OpenProject account does not require changing any
configuration file: it is done directly from inside Decentraland, the first time the assistant is
used (see section 5.3).

---

## 4. Starting the middleware (API)

From the project root, with the virtual environment active:

```bash
uvicorn api:app --reload
```

The server starts on `http://127.0.0.1:8000`. To check that it is running, open
`http://127.0.0.1:8000/docs` in a browser: FastAPI's automatic documentation should appear.

Ollama must already be running in the background before starting the API (it usually starts on
its own after installation; otherwise start it with `ollama serve`).

---

## 5. Starting the Decentraland scene

### 5.1 Installation (first time only)

```bash
cd ScenaDC/decenetraland-scene
npm install
```

### 5.2 Starting the preview

With the middleware already running (step 4), from the scene folder:

```bash
npm start
```

The command automatically opens a browser window with the scene preview. Walking around the
scene, the assistant is the clickable NPC: clicking it opens the dialogue panel at the bottom.

### 5.3 Linking your OpenProject account (once, per person)

The assistant panel identifies the user from the Decentraland wallet (in local preview, a session
identifier). The first time it is used, if the wallet is not yet linked to any OpenProject
account, the reply says so and an **"Open link page"** button appears: clicking it opens a page in
the system browser where you paste your OpenProject API key (generated as described in the
Configuration section). From that point on, questions asked from that wallet will run with the
permissions of that OpenProject account.

The pasted key stays server-side only and never returns to the browser or to the scene.

---

## 6. Usage

1. Start Ollama (if not already running).
2. Start the middleware (step 4).
3. Start the scene (step 5.2).
4. Click the assistant, link your account if prompted (step 5.3), type a question (e.g. *"which
   tasks is Mario assigned in Mobile App?"*) and press **Ask**.

Questions can be about reading projects and tasks, and — if the linked account has the right
permissions on OpenProject — about creating or updating tasks and projects as well.

---

## 7. Important limitation: the middleware only runs locally

Inside the scene, the assistant contacts the middleware at `http://127.0.0.1:8000` (localhost),
an address that always points to whichever machine is currently running the Decentraland client,
not to a specific machine on the network. As a result, the assistant only responds if the
middleware and Ollama are running on the same machine that is currently using Decentraland —
whether in local preview or on the published version of the scene online.

For the assistant to be usable from another machine, the installation described in this README
needs to be repeated on that machine (Python, Node.js, Ollama with the two models, a `.env` file
with your own OpenProject credentials), and the middleware and scene started there: at that point
the system is self-contained on that machine and does not depend on any other.

---

## 8. Project structure (quick reference)

```
Progetto/
├── api.py                      # FastAPI — /ask, /ask_dcl, /link_wallet endpoints
├── accounts.py                 # known users → OpenProject account and key
├── permissions.py              # checks OpenProject permissions before every action
├── structured_URL_generator.py # Phase 1 — extracts parameters from the question
├── response_generator.py       # Phase 2 — generates the natural-language answer
├── json_pruning.py             # trims OpenProject data before passing it to the model
├── request_helpers.py          # HTTP calls to OpenProject
├── llm_builder.py              # builds the Ollama models
├── benchmark/                  # evaluation tooling for the system (not needed for normal use)
├── tests/                      # automated tests
├── tools/                      # support scripts (e.g. resetting/preparing test data)
├── requirements.txt
└── .env                        # to be created, see the Configuration section

ScenaDC/decenetraland-scene/
├── scene.json                  # Decentraland scene configuration
├── package.json                # npm scripts (start, build, deploy)
└── src/
    ├── assistant.tsx           # assistant NPC: UI, call to /ask_dcl, middleware address
    └── ui.tsx                  # integrates the panel into the scene's UI tree
```

---

## 9. Troubleshooting

**"could not reach the assistant" in the scene panel** — the middleware is not reachable from
the machine currently running the Decentraland client. Check that `uvicorn` is running on that
same machine and that `http://127.0.0.1:8000/docs` responds in the local browser.

**"this wallet is not linked to any OpenProject account yet"** — expected the first time a wallet
is used: use the "Open link page" button as described in step 5.3.

**The model responds very slowly to the first question** — this is expected: the first call after
starting Ollama loads the model into memory; subsequent questions are faster.

**Error when starting `npm start`** — check the Node.js version (`node -v`, must be ≥ 16) and
rerun `npm install` in the scene folder.

**Permission denied on an action that should be allowed** — permissions are read in real time from
the connected OpenProject instance (not from a middleware configuration): check that the user
actually has that permission on the project in question, within OpenProject itself.
