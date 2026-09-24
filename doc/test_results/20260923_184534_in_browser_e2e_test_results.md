# In-browser end-to-end test results

Run timestamp: 2026-09-23 18:45:34 PDT
Status: **Partially executed; executed cases recorded below. Full plan completion gate is not met.**

## Test environment

- Repository commit: `676551b5e3b38605e7f33a074e4a4d56c23bb9ab`
- Browser: Codex in-app Browser
- Server: `http://127.0.0.1:8876` using a disposable application configuration
- Synthetic records root: `/private/tmp/capital_gain_e2e_20260923/records`
- Default page viewport: 1280×720; explicit checks: 1440×900, 390×844, 320×740
- OS: macOS 27.0 (26A428); page locale `en`; timezone `America/Los_Angeles`
- Tax year: 2026 unless noted
- State: California unless noted
- Console errors on the final primary page: none observed
- No personal brokerage files or external payment submissions were used

Rule and plan hashes:

| File | SHA-256 |
| --- | --- |
| `doc/IN_BROWSER_END_TO_END_TEST_PLAN.md` | `d53328c8c31b73d61f6316d1fe1ca0f32a3f7458df900a0bc13a3f61b20aa6a6` |
| `tax_data/federal/2026.yaml` | `902b5ae27636e56d2ad44f025f6e68dedb7496ac8973f60982eb1acd8c3fc14a` |
| `tax_data/states/ca/2026.yaml` | `66b111ea6b1f157df857b9e84c1c7bf3c72b0474b2b9664be5a5f8b17a0b3018` |

## Executed California anchor cases

Expected values are from the test plan, with the CA-07/CA-08 California arithmetic independently recomputed where noted.

| Case | Expected total | Actual total | Result |
| --- | ---: | ---: | --- |
| CA-02 | $0.00 | $0.00 | PASS |
| CA-03 | $565.09 | $565.09 | PASS |
| CA-04 | $175.09 | $175.09 | PASS |
| CA-05 | $5,522.95 | $5,522.95 | PASS |
| CA-06 | $3,070.08 | $3,070.08 | PASS |
| CA-07 | $934.88 stated; $935.04 recomputed | $935.04 | PASS after oracle correction |
| CA-08 | $2,734.88 stated; $2,735.04 recomputed | $2,735.04 | PASS after oracle correction |
| CA-09 | $300.00 | $300.00 | PASS |
| CA-10 | $0.00 | $0.00 | PASS |
| CA-11 | $0.00 | $0.00 | PASS |

CA-07 and CA-08 plan arithmetic correction: `13,248 × 6% + 1,752 × 8% = $794.88 + $140.16 = $935.04`, not `$934.88`. The $0.16 total difference is in the plan ledger, not an unexplained application discrepancy.

CA-05 browser evidence matched the independent fixture ledger:

- Raw gains: short-term `$10,000.00`, long-term `$20,000.00`, total `$30,000.00`.
- Federal ordinary/short-term: `$1,200.00`.
- Federal long-term: `$2,167.50`.
- California: `$2,155.45`.
- Total: `$5,522.95`.
- Formula dialog showed taxable ordinary income `$43,900.00`, stacked long-term gain `$20,000.00`, and California taxable income `$74,294.00` with the expected bracket slices.
- Rules dialog opened and closed successfully and showed the 2026 federal and California schedules, provisional California dependent-benefit status, and source-year disclosure.

## Other executed cases

- Source toggle: excluding the HTML-like Chase filename removed its `$10,000.00` short-term lot and recalculated the dashboard to `$20,000.00` total; restoring it returned CA-05 totals.
- HTML-like filename: `html-like-<script>.csv` rendered as text; no markup executed.
- State transition: changing California to Washington immediately hid the old tax cards and showed the exact stale message, `Estimate inputs changed. Click Update estimate to calculate with these values.` The inline Update estimate control applied the change; Washington state tax displayed `$0.00`.
- Dependent benefits: CA-05 with 2 children and 1 other dependent showed a separate federal potential credit of `$4,900.00`; gains tax remained `$5,522.95`; California benefit remained informational and was not applied.
- Persistence: after reload, California, filing status, dependent counts, ordinary income, source, and the CA-05 estimate restored correctly.
- Year transition: 2025 selection switched to `records/2025/source`; a missing directory produced an actionable error. After adding the synthetic 2025 folder, only the `$100.00` 2025 lot loaded. California state tax displayed `Unavailable` with `No local 2025 tax-rule file is available for CA`; no 2026 result was reused.
- Automatic monetary update: changing ordinary income from `$50,000` to `$60,000` recalculated within the bounded wait to federal `$4,550.00`, California `$2,485.45`, total `$7,035.45`; restoring `$50,000` returned `$5,522.95`.
- Security expansion: a security expanded to show its individual lot, dates, term, and gain; it closed successfully.
- Tooltip coverage: leftmost and rightmost tax-input tooltips opened together, remained readable, and closed; 7 help summaries were present.
- Responsive layout: at 1440×900, 390×844, and 320×740 there was no horizontal overflow or clipped tax control. At 1440×900 the tax form was one 4-column row with the Update estimate button in the fourth position.
- Report: browser generated `2026-investment-gain-report.xlsx`; the download event was observed. Independent inspection found Summary, Security Summary, Realized Lots, Checks, and Source Notes sheets, 3 realized lots, and the expected synthetic source notes.
- Automated regression suite: `57 tests` passed when run with localhost socket access enabled.

## Findings and limitations

1. **P1 report recalculation concern:** the downloaded workbook contains formulas for Summary, Security Summary, and Checks, but the generated XLSX cached values were `0` for those formula cells in independent XML inspection. The raw Realized Lots and Source Notes data were present and correct. A spreadsheet recalculation/open step is required before a non-recalculating reader sees numeric summary totals. This remains open for product disposition.
2. **Test-plan oracle correction required:** CA-07 and CA-08 state `$934.88` for the California increment; independent bracket arithmetic and the displayed formula slices produce `$935.04`. Update the ledger before treating those rows as exact unchanged expectations.
3. The full completion gate was not claimed. Not executed in this run: all federal/California threshold grids, NUM-01 through NUM-10, DEP-02 through DEP-08, delayed-response and injected-failure races, two-tab concurrency, malformed/empty/missing source matrix, full Schwab cases, auto-detect/direct-folder matrix, all report replacement/archive cases, 200% zoom, complete keyboard/focus audit, Safari/WebKit, Firefox, offline/network inspection, and non-California regression matrix.

## Evidence files

- [Desktop screenshot](/Users/decai/Desktop/My Apps/Capital-Gain-Estimate-Tax-Calculator/doc/test_results/20260923_184534_desktop.png)
- [Mobile screenshot](/Users/decai/Desktop/My Apps/Capital-Gain-Estimate-Tax-Calculator/doc/test_results/20260923_184534_mobile.png)
- [Narrow screenshot](/Users/decai/Desktop/My Apps/Capital-Gain-Estimate-Tax-Calculator/doc/test_results/20260923_184534_narrow.png)
- Downloaded workbook: `/private/tmp/capital_gain_e2e_20260923/records/2026/reports/2026-investment-gain-report.xlsx`

All fixtures and configuration were disposable synthetic data under `/private/tmp/capital_gain_e2e_20260923`.
