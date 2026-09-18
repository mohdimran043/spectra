"""End-to-end acceptance scenarios.

This package marker exists so the scenario modules can share fixture constants
via ``from .conftest import ...``; without it pytest imports each test file as a
top-level module and the relative import fails at collection time.
"""
