# Hackathons Tracker

An AI-powered dashboard for discovering and judging hackathon projects.

Hackathons Tracker scrapes winning Devpost projects, stores them in PostgreSQL, evaluates each project with an LLM, and presents the results in a clean web UI. It helps you quickly compare hackathon ideas, ratings, categories, tech stacks, strengths, and improvement areas.

## Live Demo

The demo is running live at:

https://hackathons-tracker-gitanos-production.up.railway.app/

## What It Does

- Scrapes winning Devpost projects with videos.
- Opens project detail pages and extracts descriptions, tech stacks, GitHub links, and demo links.
- Uses OpenAI or Gemini to judge each project with a strict hackathon rubric.
- Stores hackathons, projects, and evaluations in PostgreSQL.
- Shows projects in a FastAPI-powered web dashboard.
- Lets you search, sort, and filter by category, rating range, hackathon, source, links, and tech stack.
- Supports manually adding projects.
- Lets you delete projects from the visible list so they are skipped if scraped again.

## Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy async ORM
- Uvicorn
- Nodriver + Chromium for scraping
- OpenAI API or Gemini API for evaluations
- Docker / Docker Compose

## Project Structure

```text
app/
  main.py          FastAPI app and API routes
  pipeline.py      Scrape, save, and evaluate workflow
  scraper.py       Devpost scraper
  evaluator.py     LLM judging logic
  models.py        SQLAlchemy models
  db.py            Database setup and sessions
  static/          Frontend HTML, CSS, and JavaScript
scripts/
  init_db.py       Initialize database tables
  run_pipeline.py  Run the scrape/evaluate pipeline from the CLI
Dockerfile
docker-compose.yml
requirements.txt
```

## Running Locally With Docker

1. Create a `.env` file with at least one LLM API key:

```env
OPENAI_API_KEY=your_openai_key
# or
GEMINI_API_KEY=your_gemini_key
```

2. Start the app and database:

```bash
docker compose up --build
```

3. Open the dashboard:

```text
http://localhost:8000
```

The app will create the database tables automatically on startup.

## Useful Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://hackathons:hackathons@localhost:5432/hackathons` | PostgreSQL connection string |
| `DEVPOST_SEARCH_URL` | Devpost winners search URL | Source page for scraping |
| `MAX_PROJECTS` | `25` | Maximum number of projects to scrape |
| `SCRAPER_DELAY_SECONDS` | `1.5` | Delay between scraper requests |
| `CHROMIUM_PATH` | `/usr/bin/chromium` | Chromium executable path |
| `CHROMIUM_HEADLESS` | `true` | Run Chromium in headless mode |
| `LLM_PROVIDER` | `auto` | `auto`, `openai`, or `gemini` |
| `OPENAI_API_KEY` | empty | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model used for judging |
| `GEMINI_API_KEY` | empty | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model used for judging |

## API Endpoints

- `GET /` - Web dashboard
- `GET /add` - Manual project form
- `GET /projects` - List stored projects
- `POST /projects` - Add a manual project
- `DELETE /projects/{project_id}` - Hide/delete a project from the visible list
- `POST /trigger-pipeline` - Start scraping and evaluation in the background
- `GET /jobs/{job_id}` - Check pipeline job status
- `GET /jobs/latest` - Get the latest pipeline job

## Running The Pipeline Manually

With the app environment configured, you can run:

```bash
python scripts/run_pipeline.py
```

This scrapes projects, saves them to the database, evaluates them with the configured LLM provider, and prints a JSON summary.

## Pitch

Hackathons Tracker is like a scout and judge for hackathon projects. It finds winning submissions, analyzes what makes them strong or weak, and turns them into a searchable dashboard so builders can learn from real winners and spot better project ideas faster.
