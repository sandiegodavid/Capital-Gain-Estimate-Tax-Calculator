# Capital Gain Estimate Tax Calculator

A private, local web app for reviewing realized investment gains, creating an auditable Excel workbook, and exploring a planning-only estimated tax from reviewed AI-provided bracket schedules. Brokerage data and saved guidance stay on your Mac.

## Dashboard

![Capital Gain Estimate Tax Calculator dashboard](<doc/screenshots/Screenshot 1.png>)

### Estimated tax, carryovers, and payment actions

![Estimated tax inputs, carryover losses, results, and payment actions](<doc/screenshots/Screenshot 4.png>)

### Rate bracket review

![Rate bracket review with selectable responses, separate federal and state deductions, and provider controls](<doc/screenshots/Screenshot 2.png>)

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
    └── reports/      # Excel reports and AI guidance
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

## Estimated Tax and AI rate guidance

The Estimated Tax section accepts state residence, filing status, number of dependents, other ordinary taxable income, and separate short-term and long-term capital-loss carryovers. These selections are saved locally and restored when the dashboard opens. Supported filing statuses include single, head of household, married filing jointly, and married filing separately.

Carryovers offset gains of the same term first. Any remaining net capital loss can reduce ordinary income up to the annual planning cap: $3,000 for single and married-filing-jointly filers, or $1,500 for married-filing-separately filers. The current estimate applies the same carryover treatment to state tax; state-specific rules may differ.

Choose **Show rate brackets** to open the Rate bracket window. It loads saved responses matching the selected state, filing status, and number of dependents. Select an AI provider there to request new guidance or open that provider's settings:

- ChatGPT / OpenAI API
- Google Gemini API
- OpenRouter API

The Rate bracket window retains up to three valid saved responses for the selected tax profile and indicates when that maximum has been reached. It presents separate federal ordinary, federal long-term, and state bracket tables, plus distinct federal and state standard deductions. You can edit bracket limits, rates, and deductions; add or remove brackets; select a response; or discard a response and request a replacement. Edited responses are marked as manually updated and validated before they are saved.

When you select **Use**, all valid reviewed responses are saved as YAML in:

```text
reports/ai-rate-guidance/
```

The selected response is marked clearly. The dashboard maps its approved brackets to your income level, estimates federal and state tax, and offers **See exact formula**. Federal short-term gain/loss is treated as ordinary income; the formula view explains the separate deductions, carryover treatment, and bracket calculations.

Official federal and supported state payment links come from `reference/income_tax_payment_websites.yaml`. Verify amounts, deadlines, and payment destinations before making a payment.

### AI configuration

Use `config.example.json` as the safe template. Add only provider keys and model names you intend to use to `config.local.json`, for example:

```json
{
  "ai_provider": "gemini",
  "gemini_api_key": "your_key",
  "gemini_model": "gemini-3.7-flash"
}
```

Environment variables override local keys when set: `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `OPENROUTER_API_KEY`.

AI guidance is optional and requires internet access. Requests go to the provider you select. The terminal logs diagnostic request and response information, while the dashboard never displays API keys or key fingerprints.

## Updating and development

After replacing app files with an updated version, run `setup.command` to refresh dependencies. Run automated checks from the app folder with:

```bash
python3 -m unittest discover -s tests -v
```

`capital_gain_estimate_tax_calculator.py` is the entry point. The `capital_gain_estimate_tax_calculator/` package separates brokerage normalization, Excel export, dashboard rendering, tax formulas, AI providers, guidance validation and storage, local settings, and payment links.

## Important limitations

This is a planning and review tool, not tax, legal, accounting, investment, or payment advice. It does not cover every tax rule, deduction, credit, surtax, carryover, or brokerage adjustment. In particular, the current state carryover calculation is a planning assumption rather than a state-by-state tax-rule engine. Review imported data, guidance, calculations, and payment decisions with qualified professionals where appropriate.

See the in-app [Terms of Service](http://127.0.0.1:8765/terms) for the complete disclaimer, no-warranty, and limitation-of-liability terms. Developed by DC Technology Consulting for open-source, free use.
