# Repository Guidelines

## Project Structure & Module Organization
Although the repository currently only holds documentation, treat the root as a lean CLI service layout. Place runtime code under `src/` and split it by responsibility: `src/cli/` for argument parsing, `src/pingers/` for protocol-specific probers, and `src/models/` for typed payloads shared across workers. Host inventories belong in `assets/hosts/`, while defaults and feature flags live in `config/`. Keep tests beside their scope (`tests/unit/` mirrors `src/` packages, `tests/integration/` drives real network calls). Use `docs/` for ADRs and architecture notes.

## Build, Test, and Development Commands
Develop against Python 3.11+ in a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`. Track runtime dependencies in `requirements.txt`, put tooling in `requirements-dev.txt`, and install with `python -m pip install -r requirements-dev.txt`. Run `pytest` regularly and manually exercise the CLI with `python -m multi_ping.cli --hosts assets/hosts/sample.yml` before opening a PR. Enforce consistency via `black src tests` and `ruff check src tests`.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation and explicit type hints. Modules remain lowercase with underscores (`src/pingers/icmp_agent.py`), public classes are PascalCase, and internal helpers stay snake_case. CLI flags use kebab-case, while JSON or dict keys use snake_case. Keep constants in `UPPER_SNAKE_CASE` inside `config.py`, and store protocol-specific defaults next to their implementations.

## Testing Guidelines
Use `pytest` fixtures to stub sockets and wrap real ICMP or HTTP sends behind the `integration` marker. Name tests `test_<function>_<behavior>` (e.g., `test_dispatch_targets_batches_hosts`). Maintain ≥90% coverage for `src/`, and block merges without at least one integration test proving multi-host scheduling. Store packet captures, mock responses, and host samples under `tests/data/` so CI never hits production networks.

## Commit & Pull Request Guidelines
Adopt Conventional Commit prefixes (`feat:`, `fix:`, `docs:`, `chore:`) to keep history searchable. Keep commits focused and include a short rationale when touching networking code or concurrency primitives. Each PR should summarize the change, link any tracking issue, list the commands you ran (`pytest`, `black`, `ruff`, manual CLI check), and attach CLI snippets if user-visible output changed. Tag reviewers who own the affected directories and wait for at least one approval before merging.

## Security & Configuration Tips
Never hard-code credentials, API tokens, or real network ranges. Read sensitive values from `.env` via `config/settings.py`, and check only anonymized host inventories into `assets/hosts/`. When sharing packet captures for debugging, sanitize them first with `tcpdump -r capture.pcap -w redacted.pcap` so private traffic stays local.
