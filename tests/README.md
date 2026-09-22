# Test suite

Run the complete suite from the repository root:

```sh
.venv/bin/python -m unittest discover -s tests
```

`tests/integration/` covers package data, application workflows, HTTP routes,
rendering, and workbook output. Test classes name the boundary under test so a
failure identifies the responsible area without relying on test execution order.
