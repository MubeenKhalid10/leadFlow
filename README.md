# LeadFlow

Turn messy lead data into clean, campaign-ready contacts.

LeadFlow ingests a raw lead file, standardises and cleans it, filters out
unwanted contacts, and suppresses anyone already in your **Master** lists or
who has previously **bounced** — then lets you export the campaign-ready file.

Master and Bounce suppression data live in **PostgreSQL** (organised as named
lists), so you no longer upload those files on every run. After a cleaning run
you can push the freshly cleaned contacts back into a Master list for next time.

---

## What changed (database edition)

- **Master & Bounce data are stored in PostgreSQL**, not uploaded each run.
- Both are organised as **named lists** (e.g. `Q1 Campaign`, `Hard Bounces 2025`),
  and you choose which lists to suppress against on each run.
- A new **🗄️ Manage Suppression Database** page lets you import files into the
  database, view list sizes, and delete lists.
- After cleaning, you can **save the cleaned contacts into a Master list**
  (full records, deduped by email).

---

## Prerequisites

- Python 3.11+
- A running **PostgreSQL** server (local is fine to start)

## 1. Install PostgreSQL (local)

**Windows:** install from https://www.postgresql.org/download/windows/ and note
the password you set for the `postgres` user during setup.

**macOS (Homebrew):** `brew install postgresql@16 && brew services start postgresql@16`

**Linux (Debian/Ubuntu):** `sudo apt install postgresql && sudo service postgresql start`

The app will **create the `leadflow` database automatically** on first run if the
connecting user is allowed to. If not, create it once manually:

```bash
createdb leadflow
```

## 2. Configure the connection

Connection settings are read from `.streamlit/secrets.toml`. Copy the example
and edit it to match your PostgreSQL install:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

```toml
[postgres]
host = "localhost"
port = "5432"
dbname = "leadflow"
user = "postgres"
password = "your-local-password"
```

You can also override any value with environment variables: `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`.

> `.streamlit/secrets.toml` is git-ignored so your credentials never get committed.
> When you move to a cloud database (Neon, Supabase, RDS, …), just change the
> values here (add `sslmode = "require"` if your provider needs SSL) — no code changes.

## 3. Install dependencies & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The tables (`master_lists`, `master_contacts`, `bounce_lists`, `bounce_emails`)
are created automatically on first run.

---

## Typical workflow

1. **First time:** open **🗄️ Manage Suppression Database** and import your
   existing master file(s) and bounce file(s) into named lists.
2. On the main page, upload a **raw lead file**.
3. Confirm the column mapping and pick which **Master** and **Bounce** lists to
   suppress against.
4. **Run the cleaning pipeline** and review the results.
5. **Download** the campaign-ready file (and any country/industry splits).
6. Optionally **save the cleaned contacts** into a Master list so they're
   suppressed on future runs.

---

## Project layout

| File | Purpose |
|------|---------|
| `app.py` | Main cleaning page (upload → clean → suppress → export → update master) |
| `pages/1_Manage_Suppression_Database.py` | Import / view / delete Master & Bounce lists |
| `db.py` | PostgreSQL layer (schema, lists, upserts, suppression queries) |
| `dataio.py` | Shared file loading, validation, and column mapping |
| `theme.py` | Shared UI theme (CSS, top bar, section headers) |
| `data/countries.json` | Country/city reference used for the location split |
