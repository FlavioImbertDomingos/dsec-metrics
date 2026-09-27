"""Domain models, schemas, the evaluator and threshold logic.

This package is pure Python: no I/O, no database and no network. Everything else in
the project may import it; it imports nothing else from the project. The rule is
enforced by ``tests/unit/test_import_boundaries.py``. Contents arrive in M1.
"""
