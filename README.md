# Capital Gain Estimate Tax Calculator

A private, local web app for reviewing realized investment gains, creating an auditable Excel workbook, and exploring a planning-only estimated tax from bundled, year-versioned federal and state rules. Brokerage data stays on your Mac.

## Dashboard

![Capital Gain Estimate Tax Calculator dashboard](<doc/screenshots/Screenshot 1.png>)

### Estimated tax, carryovers, and payment actions

![Estimated tax inputs, carryover losses, results, and payment actions](<doc/screenshots/Screenshot 4.png>)

### Exact tax formula

![Exact tax formula showing taxable income and bracket calculations](<doc/screenshots/Screenshot 3.png>)

## Quick start

1. Double-click `setup.command` once. It creates a local `.venv` and installs every dependency listed in `requirements.txt`.
2. Copy `config.example.json` to `config.local.json`, then add your local settings. Do not share `config.local.json`; it is ignored by Git.
3. Double-click `launch.command`, or run:

   ```bash
   python3 capital_gain_estimate_tax_calculator.py
   ```

   The dashboard opens in your browser. If it does not, browse to `http://127.0.0.1:8765`.
4. Choose the sale year, confirm the source folder, and click **Load data**.

The source field accepts the overall records folder, a particular year folder,
the conventional `source` folder, or a folder containing brokerage CSV files.
Leave the sale year on **Auto-detect** to use the latest year found in the
selected source data.

On a new Apple-silicon Mac, `setup.command` checks for Python 3.10 or newer and explains how to install it if necessary. Run it again after a dependency update. The `.venv` folder is disposable and ignored by Git.

If macOS blocks a `.command` file, Control-click it, choose **Open**, and confirm.

## Organizing records

Set `realized_gains_root` in `config.local.json` to the folder named `Realized Gains`. In the dashboard, **Choose folder** accepts either that folder or its immediate parent. The year selector then uses the matching `source` and `reports` folders automatically.

```text
Realized Gains/
└── 2026/
    ├── source/       # Brokerage CSV exports
    └── reports/      # Excel reports
```

Keep brokerage exports and generated files outside the application folder. Local configuration, source files, reports, audit files, manifests, and workbooks are ignored by Git.

## Dashboard and Excel report

The dashboard displays the selected year's total, short-term, and long-term realized gain/loss; included sources; and a Security Summary. Expand a security to review each individual realized lot.

Select **Create Excel report** to create `YYYY-investment-gain-report.xlsx` in the report folder. You can download it from the dashboard. The app can archive an existing report before replacement and optionally keep normalized CSV and JSON audit files.

The workbook includes **Summary**, **Security Summary**, **Realized Lots**, **Checks**, and **Source Notes**. Numeric values are true Excel numbers for correct sorting, and the checks sheet contains reconciliation and data-type checks.

### Supported brokerage exports

- Chase CSV files with `Account Name`, `Market Cost/Proceeds USD`, and `Total Realized Gain Loss USD`.
- Fidelity CSV files with `Account`, `Symbol(CUSIP)`, `Short Term Gain/Loss`, and `Long Term Gain/Loss`.
- Charles Schwab realized gain/loss CSV files, including exports with a report-title row before the headers. Required fields include `Symbol`, `Closed Date`, `Proceeds`, `Cost Basis (CB)`, and `Total Gain/Loss ($)`; the file name may also include `Schwab`.

Charles Schwab's export does not provide acquisition dates. The workbook uses the closed date as an acquisition-date placeholder and calls this out in **Source Notes**. A numeric `Long Term (LT) Gain/Loss ($)` value classifies a lot as long-term, while a numeric `Short Term (ST) Gain/Loss ($)` value classifies it as short-term; blank or dash values are not treated as a term classification. Its reported short-term, long-term, total gain/loss, and disallowed-loss fields are retained for reconciliation.

Exact duplicate-looking rows are kept because they may be separate tax lots. Confirm final figures against brokerage documents.

## Estimated tax from local jurisdiction rules

The Estimated Tax section accepts state residence, filing status, qualifying children, other dependents, other ordinary taxable income, and separate short-term and long-term capital-loss carryovers. These selections are saved locally and restored when the dashboard opens. Supported filing statuses include single, head of household, married filing jointly, and married filing separately.

Carryovers offset gains of the same term first. Any remaining net capital loss can reduce ordinary income up to the annual planning cap: $3,000 for most filing statuses or $1,500 for married filing separately. The current estimate applies the same carryover treatment to state tax; state-specific rules may differ.

The calculator loads federal rules from `tax_data/federal/<year>.yaml` and state rules from `tax_data/states/<state>/<year>.yaml`. Choose **View tax rules** to inspect the selected filing status's:

- ordinary-income and capital-gain brackets;
- federal and state standard-deduction information; and
- credit and dependent-benefit information.

The rule window is read-only. Credits are displayed but are not automatically applied when eligibility requires information the calculator does not collect, such as a child's age, earned income, MAGI adjustments, or other statutory tests.

The dashboard estimates federal and supported state tax and offers **See exact formula**. Federal short-term gain/loss is treated as ordinary income; the formula view explains deductions, carryover treatment, state capital-gain exclusions encoded by the data, and bracket calculations. If a state YAML file marks a required rule as unsupported, the dashboard reports the state estimate as unavailable instead of approximating it.

Official federal and supported state payment links are stored alongside each jurisdiction's annual tax data in `tax_data/`. Verify amounts, deadlines, and payment destinations before making a payment.

## Updating and development

After replacing app files with an updated version, run `setup.command` to refresh dependencies. Run automated checks from the app folder with:

```bash
.venv/bin/python -m unittest discover -s tests
```

Development-only quality gates are configured in `pyproject.toml` and installed with:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff format --check .
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
.venv/bin/python -m compileall -q capital_gain_estimate_tax_calculator
```

`capital_gain_estimate_tax_calculator.py` is the entry point. The package keeps these boundaries explicit:

- `tax_rules.py`, `tax_domain.py`, and `tax_estimate.py` load validated local rules and calculate estimates.
- `state_dependent_benefits.py` evaluates only typed, explicitly supported state benefits.
- `brokerage_parsing.py` supplies shared CSV primitives; `normalizer.py` owns brokerage registration and mapping.
- `report_document.py` builds report meaning; `excel_export.py` renders that prepared document as a workbook.
- `web_actions.py`, `folder_actions.py`, and `web_http.py` adapt application actions to local HTTP; `views/` renders prepared view models.

### Extending tax benefits and brokerages

To add a state dependent benefit, add the complete typed entry to the state's annual YAML file, including eligibility basis, income measure, calculation method, phaseout support, source metadata, status, and explicit calculation support. Add calculation code only when every required eligibility input and formula is encoded; otherwise mark it informational or unsupported. Extend the relevant data and calculator tests before changing a result.

To add a brokerage, implement its CSV mapper and register a `FunctionBrokerageNormalizer` with its schema name, filename markers, required headers, source note, and mapper. Add independent detection and normalization tests. Existing brokerage normalizers and the report-generation workflow do not need changes.

## Important limitations

This is a planning and review tool, not tax, legal, accounting, investment, or payment advice. It does not cover every tax rule, deduction, credit, surtax, carryover, or brokerage adjustment. In particular, the current state carryover calculation is a planning assumption rather than a state-by-state tax-rule engine. Review imported data, tax rules, calculations, and payment decisions with qualified professionals where appropriate.

See the in-app [Terms of Service](http://127.0.0.1:8765/terms) for the complete disclaimer, no-warranty, and limitation-of-liability terms. Developed by DC Technology Consulting for open-source, free use.
