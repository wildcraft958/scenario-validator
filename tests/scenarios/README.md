# Scenario Fixtures

This directory is reserved for complete RoadRunner export fixtures.

The current automated integration coverage creates deterministic synthetic
scenario folders at test runtime in `tests/test_contract.py`. Those fixtures are
synthetic and are used only to prove validator behavior, report generation,
security handling, and CLI exit-code rules.

Real RoadRunner runs supplied with this repository live under `examples/`.
They are validated by smoke tests, but they are incomplete against the full
scenario directory contract because they do not include `.rd`, scenario `.xml`,
`.txt`, or `TA.xml` files.
