# Harbour

**From uncertainty to a clear next step.**

Harbour is an independently developed public-benefits navigator. It turns a person's situation into a ranked, plain-language action plan and helps close the loop between finding a service, contacting it, and confirming that help arrived.

Repository: <https://github.com/jawaharlaldoon-bit/Harbour>

Live demo: <https://harbour-benefits-navigator.onrender.com>

## What Harbour does

- Accepts typed or browser-transcribed descriptions in multiple languages.
- Extracts needs, urgency, language, and confidence using an auditable intake engine.
- Asks relevant follow-up questions before matching.
- Ranks eligible community and federal programs with clear next steps.
- Uses mixed-integer linear programming to allocate scarce resources while enforcing a demographic-parity constraint.
- Tracks saved cases and escalates broken referrals to a vulnerability-prioritized caseworker queue.
- Gives organizations a capacity, demand-forecast, and outcome dashboard.
- Continues to work without external credentials by using bundled resources, local persistence, and rule-based chat responses.

## Architecture

```text
harbour/
├── README.md
├── render.yaml
└── harbour-app/
    ├── app.py                    # FastAPI application and API routes
    ├── db.py                     # Optional Supabase connection
    ├── engine/
    │   ├── intake_nlp.py         # Auditable intake and confidence gate
    │   ├── followups.py          # Eligibility follow-up questions
    │   ├── milp_solver.py        # Fair resource-allocation model
    │   ├── caseworker.py         # Vulnerability-prioritized escalation queue
    │   ├── demand_forecast.py    # Aggregate resource-demand forecast
    │   └── text_tools.py         # Plain-language and readability helpers
    ├── static/index.html         # Responsive single-page interface
    ├── data/resources.json       # Bundled demonstration resources
    ├── scraper.py                # Seed and approved live-data ingestion
    ├── supabase_schema.sql       # Optional persistent-storage schema
    ├── test_core.py              # Core engine tests
    └── test_api.py               # Credential-free API smoke tests
```

## Run locally

Harbour requires Python 3.11 or newer.

```powershell
cd harbour-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scraper.py --seed
python test_core.py
python test_api.py
uvicorn app:app --reload
```

Open <http://127.0.0.1:8000>. Interactive API documentation is available at <http://127.0.0.1:8000/docs>, and the deployment health check is at <http://127.0.0.1:8000/health>.

## Configuration

Harbour runs without API keys. To enable optional integrations, copy `harbour-app/.env.example` to `harbour-app/.env`. The example includes Harbour's public Supabase project URL; add a newly issued server-side key only to the ignored `.env` file or your deployment environment.

| Variable | Purpose | Required |
| --- | --- | --- |
| `GEMINI_API_KEY` | AI-assisted chat responses | No |
| `SUPABASE_URL` | Persistent shared database URL | No |
| `SUPABASE_KEY` | Server-side Supabase key | No |

Without Supabase, cases and organization updates use local JSON files. For persistent deployment, run `harbour-app/supabase_schema.sql` in Supabase and then seed the resource table:

```powershell
python seed_supabase.py
```

The seed command replaces the contents of Harbour's `resources` table. Use it only with the intended Harbour database.

## Demo access

The organization and caseworker screens use clearly labeled browser-only demonstration credentials:

- Organization: `org@harbour.local` / `harbour-demo`
- Caseworker: `caseworker@harbour.local` / `harbour-demo`

These credentials are not production authentication. Production access requires a real identity provider and server-enforced authorization.

## Data and responsible use

- Harbour does not upload or store audio. The browser may use its own speech service; Harbour receives the resulting transcript.
- A plan is stored only when the person chooses to save a case.
- Contact details are optional and are stored only for requested follow-up.
- The matching engine is preparatory: it recommends and prioritizes resources but does not make final eligibility decisions.
- Aggregate demand forecasting is separated from individual matching and does not assign risk scores to people.
- Bundled resources and dashboard outcomes are demonstration data. Replace them with an approved official resource feed before operational use.

## Deployment

The repository-root `render.yaml` is ready for a Render Blueprint deployment. Add optional environment variables through the hosting provider rather than committing secrets.
