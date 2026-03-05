# Contributing to Razi

Thank you for your interest. Razi is in early development. Contributions that align with the v1 scope are very welcome.

## What we want
- Bug fixes
- Additional test fixtures and example inputs
- Documentation improvements
- Policy rule edge case coverage

## What is out of scope for v1
- New operators beyond evidence.index and synth.json
- New model providers (planned for v1.2)
- UI or SDK abstractions
- Generalization of the .aispec format

## Process
1. Open an issue first for anything non-trivial
2. Fork, branch, commit with clear messages
3. All tests must pass: `pytest tests/ -v`
4. Lint must pass: `ruff check razi/ tests/`
5. Open a PR against main

## Code style
- Black formatting (enforced by ruff)
- Type annotations on all public functions
- Docstrings on all public functions and classes

By contributing you agree your code is licensed under Apache 2.0.
