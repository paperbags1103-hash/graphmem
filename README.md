# graphmem

Minimal setup for the CLI, tests, and example scaffold.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
graphmem init --memory MEMORY.md --db .graphmem --auto
graphmem status --db .graphmem
pytest
python examples/quickstart.py
```
