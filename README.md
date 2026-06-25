# PromptEvo

PromptEvo is an advanced AI safety and red-team automation framework built in Python. It helps audit LLMs by orchestrating attacker, scout, analyst, and target agents, and it includes a Streamlit dashboard for interactive analysis.

## Features

- Modular AI audit engine with agent coordination.
- Streamlit dashboard for session review and report exploration.
- Configurable model adapters for Ollama, OpenAI, Groq, and other providers.
- Safe local-only operation with `.env` configuration.
- Reproducible setup using `requirements.txt` or `pyproject.toml`.

## Requirements

- Python 3.11 or newer
- Git
- `pip` package manager

## Setup

1. Create a Python virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Copy the environment template and fill in your keys:

```powershell
copy .env.example .env
```

4. Edit `.env` and set provider API keys and model settings.

## Running the engine

To see available options:

```powershell
python main.py --help
```

To run the main audit engine:

```powershell
python main.py
```

## Dashboard

Launch the Streamlit dashboard:

```powershell
streamlit run dashboard/streamlit_app.py
```

Then open the local URL printed by Streamlit.

## Project files

- `main.py` — CLI entry point for PromptEvo.
- `config.py` — environment loading and runtime settings.
- `api.py` — API support and adapter registration.
- `dashboard/` — Streamlit dashboard and UI components.
- `agents/` — agent modules and runtime logic.
- `core/` — orchestration, state, and engine internals.
- `data/` — datasets, prompts, and local model resources.

## GitHub readiness

This repository is prepared for GitHub by:

- ignoring local environment files (`.env`)
- ignoring virtual environment artifacts (`.venv/`)
- ignoring runtime logs and caches
- providing `.env.example` with placeholder configuration

> Do not commit `.env`, `.venv/`, runtime reports, or local logs.

## Notes

- Keep secrets out of the repository.
- `data/` contains needed project resources, but local runtime outputs such as `data/audit_runs/` and `data/memory/` are ignored.
- If you use `dashboard/`, you may also install optional packages from `dashboard/requirements-dashboard.txt`.
