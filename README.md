# Codenova

Codenova reads your Gmail (read-only), pulls out the things you actually have
to do, ranks them, and sets aside everything that is only information,
including mail meant for a class you're not in.

```
codenova/
├── backend/     FastAPI: Google OAuth, Gmail scanning, task extraction, class-aware ranking
└── frontend/    React + TypeScript (Vite)
```

## Sections

Every feature lives in exactly one section.

| Section | What it's for |
|---|---|
| **Now** | What needs doing right now: overdue, due today, then the next few by priority. A task appears in only one of those lists. |
| **Planner** | The next seven days by deadline, plus tasks with no date yet. |
| **FYI** | Mail worth knowing about that isn't your work: other classes' notices, announcements, newsletters, automated mail. "This is mine" turns an item into a task. |
| **Sync** | Scan Gmail (default window or chosen dates), watch progress, re-run or remove past scans, scan defaults. |
| **Profile** | Your classes, important and ignored senders, sign out, and your data (delete imported data, disconnect Gmail, delete account). |

Opening any task shows its one detail sheet (why it's ranked, edit, snooze,
done / not mine / dismiss). The notification bell and the **Ask** assistant
live in the top bar.

## Class-aware priority

Add the classes you're in under **Profile → Your classes** (for example
`Class A`, `SY-B` or `CS201`). On every scan, `backend/app/ai/audience.py`
reads the subject and opening lines of each email:

- **Addressed to another class** ("Class B students…", "[SY-B] …") → never
  becomes a task. It goes to FYI as "For Class B, not your class".
- **Addressed to your class** → ranked a little higher, with "Addressed to
  your class" as the first reason.
- **No class named** → ranked as usual.

Changing your classes re-ranks existing tasks immediately.

There is no demo/local user mode. Every session starts with a real Google
sign-in. You need a Google Cloud project with OAuth credentials before the
app will run. Full setup below.

---

## Part 1 — Google Cloud Console setup

### 1. Create a project
1. Go to https://console.cloud.google.com/
2. Top-left project dropdown → **New Project**
3. Name it (e.g. `codenova`) → **Create**
4. Make sure it's selected in the top dropdown before continuing

### 2. Enable the Gmail API
1. Left sidebar → **APIs & Services** → **Library**
2. Search "Gmail API" → click it → **Enable**

### 3. Configure the OAuth consent screen
1. **APIs & Services** → **OAuth consent screen**
2. User type: **External** (unless you have a Google Workspace org and want **Internal**) → **Create**
3. Fill in:
   - App name: `Codenova`
   - User support email: your email
   - Developer contact email: your email
4. **Save and Continue**
5. **Scopes** screen → **Add or Remove Scopes** → search and check:
   - `https://www.googleapis.com/auth/gmail.readonly`

   If the scope doesn't appear in the list, it's because Gmail API isn't
   enabled yet on this project — go back to step 2, enable it, then refresh
   this page and reopen "Add or remove scopes".
   → **Update** → **Save and Continue**
6. **Test users** screen (this matters — while the app is in "Testing" status,
   only these accounts can sign in) → **Add Users** → add every Gmail address
   that should be able to use the app → **Save and Continue**
7. Review → **Back to Dashboard**

You can leave the app in **Testing** status indefinitely for personal/team
use — no need to submit for Google verification unless you want arbitrary
public users to sign in.

### 4. Create OAuth credentials
1. **APIs & Services** → **Credentials**
2. **Create Credentials** → **OAuth client ID**
3. Application type: **Web application**
4. Name: `Codenova Backend`
5. **Authorized redirect URIs** → **Add URI**:
   ```
   http://localhost:8000/api/auth/google/callback
   ```
   Must match `GOOGLE_REDIRECT_URI` in your `.env` exactly — no trailing
   slash, same protocol/host/port.
6. **Create**
7. A modal shows your **Client ID** and **Client Secret** — copy both now.

---

## Part 2 — Backend setup

### 5. Install dependencies

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

> **Windows + Python 3.14 users:** if `pip install` fails trying to compile
> `pydantic-core` from source (missing `link.exe`/Rust toolchain), it's
> because 3.14 is very new and some packages don't ship prebuilt wheels for
> it yet. Easiest fix: use Python 3.11 or 3.12 for this project instead —
> `py -3.12 -m venv .venv` — both have full prebuilt-wheel coverage for
> everything in `requirements.txt`.

### 6. Generate secrets

```bash
# Encrypts the Gmail refresh token at rest — required
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"

# Signs the session cookie — required
python -c "import secrets;print(secrets.token_hex(32))"
```

### 7. Configure `.env`

```bash
cp .env.example .env
```

Edit `backend/.env`:

```env
APP_SECRET_KEY=<output from secrets.token_hex(32) above>
FERNET_KEY=<output from Fernet.generate_key() above>
FRONTEND_URL=http://localhost:5173
DATABASE_URL=sqlite:///./workday_agent.db

GOOGLE_CLIENT_ID=<Client ID from step 4>
GOOGLE_CLIENT_SECRET=<Client Secret from step 4>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
```

`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are **required** — the backend
will return a clear 500 error on sign-in attempts until these are set (see
"No local fallback" below).

### 8. Run the backend

```bash
uvicorn app.main:app --reload --port 8000
```

Runs at `http://localhost:8000`. Interactive API docs at
`http://localhost:8000/docs`.

---

## Part 3 — Frontend setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Runs at `http://localhost:5173`.

---

## Part 4 — Sign in and run the agent

1. Open `http://localhost:5173`
2. Click **Sign in with Google** — redirects to the real Google consent screen
3. Sign in with an account you added as a **test user** in step 3.6 (any
   other Google account will be rejected while the app is in Testing status)
4. You'll likely see "Google hasn't verified this app" — expected for apps in
   Testing mode. Click **Advanced** → **Go to Codenova (unsafe)**
5. Consent screen shows the `gmail.readonly` scope → **Continue**
6. You're redirected back through `http://localhost:8000/api/auth/google/callback`,
   which sets your session cookie and lands you on the dashboard, signed in
7. Open **Profile** and add your class, then go to **Sync** and click
   **Scan the last 30 days** (capped at 150 messages), or pick From/To dates
   and click **Scan these dates**. Your tasks appear in **Now** and
   **Planner**; information-only mail appears in **FYI**.

---

## Choosing which emails get scanned

By default, `POST /api/gmail/sync` scans the last 30 days (`newer_than:30d`
in Gmail search syntax), capped at 150 messages
(`default_sync_query` / `max_messages_per_sync` in `backend/app/config.py`).

To scan a specific window instead, send a JSON body with either or both dates
(`YYYY-MM-DD`):

```bash
curl -X POST http://localhost:8000/api/gmail/sync \
  -H "Content-Type: application/json" \
  -b "workday_agent_session=<your session cookie>" \
  -d '{"start_date": "2026-07-01", "end_date": "2026-07-31"}'
```

- Both dates → scans that inclusive range (`after:2026/07/01 before:2026/08/01`)
- Only `start_date` → scans everything from that date onward
- Only `end_date` → scans everything up to and including that date
- Neither → falls back to the default `newer_than:30d` scan
- `start_date` after `end_date` → rejected with a 422 validation error

In the UI, these are the From/To fields on the **Sync** page.

## No local/demo fallback

There is intentionally no seeded local user or offline demo mode in this
codebase. Every sign-in goes through real Google OAuth
(`app/routers/auth.py`), and `POST /api/gmail/sync` requires a real
`GmailConnection` on the signed-in user — it raises a 400 rather than
returning fake data if you try to sync before connecting Gmail. If
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` aren't set, `/api/auth/google`
fails with a clear error telling you to configure them, rather than silently
letting you in.

---

## Optional: LLM-backed extraction (Gemini)

Without credentials configured, extraction runs on a deterministic rule-based
classifier (`app/ai/heuristic_extractor.py`) — fully functional, no external
calls. To use Gemini for higher-quality classification/extraction instead,
add to `backend/.env`:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

Use a Gemini API key with access to the configured model. The LLM path
(`app/ai/llm_extractor.py`) uses Gemini's schema-constrained JSON output and
automatically falls back to the heuristic
extractor if the call fails, returns invalid JSON, or credentials are only
partially set, so processing never hard-fails.

---

## Tests

```bash
cd backend
pip install pytest
python -m pytest tests
```

The tests cover class detection, ranking, and an end-to-end scan with Gmail
stubbed out (Now, Planner, FYI, re-ranking after a class change, and claiming
an FYI item).

---

## Common issues

| Symptom | Fix |
|---|---|
| `redirect_uri_mismatch` on Google's screen | The URI in Google Cloud Console must match `GOOGLE_REDIRECT_URI` character-for-character |
| "Access blocked: app not verified" with no Advanced option | Your Google account isn't in the Test users list — add it in step 3.6 |
| No refresh token returned / stuck in a re-login loop | Google only issues a refresh token on first consent. If you'd already authorized once, go to https://myaccount.google.com/permissions, remove access for the app, and sign in again |
| `Google OAuth is not configured` error on sign-in | `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are blank in `backend/.env`, or you didn't restart uvicorn after editing it |
| `No Gmail account connected` on sync | Sign-in didn't complete, or `disconnect` was called — sign in again via **Sign in with Google** |
| `pip install` fails compiling `pydantic-core` on Windows | See the Python 3.14 note in step 5 — use Python 3.11/3.12 instead |

---

## What's implemented vs. simplified from the full TRD

This is a hackathon-scale **working MVP**, not the full production system.
Simplifications, all called out in code comments at their point of use:

| TRD component | MVP implementation |
|---|---|
| PostgreSQL + pgvector | SQLite via SQLAlchemy (swap `DATABASE_URL` for Postgres — same models) |
| Celery + Redis + Pub/Sub background sync | Inline FastAPI request (`POST /api/gmail/sync`) |
| Gmail `watch()` push notifications | Stubbed (`POST /api/gmail/watch` returns 501) — poll via manual/scheduled sync instead |
| Semantic search / embeddings | SQL `LIKE` search + RapidFuzz similarity for dedup |
| OAuth refresh-token storage | Encrypted at rest (Fernet), never logged |

All **Must-Have** functional requirements (FR-01, 02, 04–11, 15, 17) and most
**Should-Have** requirements (weekly agenda, FR-12 dedup, FR-13 dependency
detection, FR-16 proactive alerts) are implemented and tested end-to-end
against a real Gmail account.
