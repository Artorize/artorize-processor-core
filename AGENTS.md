# Repository Guidelines

## Project Structure & Module Organization
- `artscraper_runner/` (CLI pipeline; tests in `tests/` at repo root)
- `artscraper_gateway/` (FastAPI gateway service; tests in `artscraper_gateway/tests/`)
- `processors/` (research/reference projects kept for documentation; not imported by default)
- Core hashing/search utilities (`blockhash`, `dhash`, `imagehash`, `google-images-download`, `hcaptcha-challenger`, `c2pa-python`, `Pillow`, etc.) are installed from PyPI—see `requirements.txt`.

## Build, Test, and Development Commands
- Create a virtualenv:
  - Windows: `python -m venv .venv && .\.venv\Scripts\Activate.ps1`
  - POSIX: `python -m venv .venv && source .venv/bin/activate`
- Install runtime dependencies from the repo root:
  - `pip install -r requirements.txt`
- Install module-specific dev extras as needed (e.g., `pip install -e artscraper_runner[dev]` if a setup is added later).
- Run tests (from the module root): `pytest -q`

## Coding Style & Naming Conventions
- Follow PEP 8; 4-space indentation; 88-100 char lines.
- Naming: `snake_case` for functions/vars, `PascalCase` for classes, `CONSTANT_CASE` for constants.
- Prefer type hints and docstrings for public APIs.
- If a module includes tooling, use it: `ruff check .`, `black .`, `isort .`, or configured `flake8`.

## Testing Guidelines
- Place tests under `tests/` (or module-specific pattern) named `test_*.py`.
- Keep fixtures small; put sample images in `tests/data/`.
- Add/adjust tests with code changes; aim to cover edge cases and error paths.
- Run `pytest -q` locally before pushing.

## Commit & Pull Request Guidelines
- Commits: concise, present tense; Conventional Commit style is welcome (e.g., `feat:`, `fix:`, `docs:`).
- PRs: include a clear description, modules touched, repro/verification steps, and linked issues. Add screenshots/output when UI/CLI behavior changes.

## Security & Configuration Tips
- Do not commit secrets or API keys; prefer environment variables and local `.env` files (ignored).
- Respect target sites' ToS/robots.txt when scraping; throttle requests.
- Avoid adding large binaries; for new assets, prefer external hosting or small test samples.

## Agent-Specific Instructions
- This file applies repo-wide. If a submodule provides its own README or AGENTS file, that module's instructions take precedence within its folder.
