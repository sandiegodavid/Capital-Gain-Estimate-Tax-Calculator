# In-browser end-to-end test plan

Status: proposed; no tests executed. Prepared September 23, 2026.

## 1. Purpose and acceptance scope

Verify the complete browser journey from synthetic brokerage CSV selection through dashboard totals, estimated tax, formula inspection, saved inputs, and report download. California is the primary jurisdiction. Verify numeric correctness using independent expected results, not merely agreement between two application screens.

This document authorizes no implementation or execution. Fixture creation, browser automation, application startup, network fault injection, and report generation described below are future work.

Current implementation references: `views/tax_panel.py`, `views/tax_output.py`, `static/dashboard.js`, `tax_estimate.py`, `tax_calculation.py`, `tax_input_parser.py`, and `tax_data/states/ca/2026.yaml` within the repository. The code has already been split into modules; earlier architecture plans are not the current layout.

Distinguish three acceptance categories:

1. **Model correctness:** the displayed gains-only planning estimate matches the documented model and reviewed fixture ledger.
2. **Tax-rule fidelity:** official sources support the parameters and disclosures. A documented approximation is not a complete tax-return calculation.
3. **Browser correctness:** each visible result belongs to the current inputs, year, sources, state, and status.

Never bless an observed output as an expected value. Suspected defects remain open findings; do not change fixtures to match them.

## 2. Source baseline and California limitations

Freeze source URLs, retrieval date, applicable tax year, source-year parameters, and rule-file hashes when execution is later authorized.

| Reference | Use |
| --- | --- |
| [IRS Revenue Procedure 2025-32](https://www.irs.gov/pub/irs-drop/rp-25-32.pdf) | Federal 2026 schedules and standard deductions |
| [California 2026 Form 540-ES instructions](https://www.ftb.ca.gov/forms/2026/2026-540-es-instructions.pdf) | Estimated-tax deduction amounts and worksheet limitations |
| [California 2025 Form 540 booklet](https://www.ftb.ca.gov/forms/2025/2025-540-booklet.html) | Prior-year schedules, credits, and tax-table requirements |
| [IRS Child Tax Credit](https://www.irs.gov/credits-deductions/individuals/child-tax-credit) | Recheck applicable-year credit eligibility and phaseout before freezing credit oracle |

California's bundled 2026 file is provisional: it uses 2025 brackets and has an unsupported dependent-credit phaseout. The 2026 worksheet specifies deductions of $5,706 for single/separate and $11,412 for joint/head-of-household/surviving-spouse filers, and refers to 2025 tax tables. Its 1% Behavioral Health Services Tax applies above $1 million taxable income. These facts require separate coverage; the fixture amounts below cover the ordinary-bracket model only.

The Form 540 booklet instructs use of the tax table at taxable income of $100,000 or less. Continuous bracket calculations can differ from table results. Require clear planning-model disclosure, or track exact table support as a separate requirement. Do not call the continuous-bracket oracle an exact Form 540 liability.

Federal and state credits are currently separate informational/potential amounts, not subtractions from the gains-only estimate. California dependent benefits must remain informational until their complete eligibility and phaseout rules are supported. Personal credits, California adjustments, NIIT, AMT, special gains, refundable ACTC/EITC, withholding, and installment calculations must not be silently implied to be included.

## 3. Future execution environment

- Use a disposable application configuration and synthetic records root; never personal brokerage files or the normal saved profile.
- Record commit, browser version, OS, rule hashes, fixture hashes, server URL, timezone, viewport, and locale. Fix year explicitly to 2026 except year-selection tests.
- Primary full suite: Chromium at 1440×900. Cross-browser critical suite: Safari/WebKit and Firefox. Verify actual Safari native controls manually if automation uses WebKit.
- Layout matrix: 2276×900, 1440×900, 1024×768, 901×900, 900×900, 801×900, 800×900, 768×1024, 390×844, and 320×740; include 200% browser zoom.
- Run normal paths against the real local HTTP application, rules, parser, and report writer. Intercept requests only for explicitly labeled failure/race scenarios.
- Prefer labels and roles for browser locators. Use existing IDs for output/form/dialog synchronization; avoid CSS-position selectors and hard-coded sleeps.
- Wait for a response associated with the submitted input snapshot and its rendered result. The current typing debounce is 350 ms; allow a bounded local completion timeout (proposed 5 seconds), not indefinite waiting.
- Isolate persisted settings between cases. Run shared-profile concurrency cases separately. No execution ordering dependency except cases explicitly testing persistence.

## 4. Independent numerical oracle

Build a reviewable fixture ledger before automation. Each entry includes input lots, expected source subtotals, ordinary income, carryovers, status, dependents, deductions, netting, taxable intervals, bracket components, credit phaseout, displayed amounts, and source citations.

Expected values must be calculated outside production functions, renderers, and production YAML loading. Transcribe reviewed source parameters into a separately reviewed ledger; an independent decimal calculator or spreadsheet may assist later. Do not invoke application calculation helpers or copy their output to establish the oracle.

For the current gains-only model, let O be other ordinary income after the allowed excess-loss offset; S and L be nonnegative post-carryover, cross-netted gains; Df and Dc be federal and California deductions. Let F and C be cumulative ordinary-bracket tax functions, and G the cumulative preferential-gain bracket function.

- Federal short-term contribution = F(max(O + S − Df, 0)) − F(max(O − Df, 0)).
- Remaining deduction = max(Df − O − S, 0).
- Taxable long-term gain = max(L − remaining deduction, 0).
- Federal long-term contribution = G(max(O + S − Df, 0) + taxable long-term gain) − G(max(O + S − Df, 0)).
- California ordinary-schedule contribution = C(max(O + S + L − Dc, 0)) − C(max(O − Dc, 0)).
- Total = federal short-term + federal long-term + supported state contribution. Credits are separate.

Use exact decimal arithmetic; round displayed final amounts to cents. Record an explicit half-cent rounding decision before implementing cent-boundary tests. Do not round bracket slices prematurely. Formula amounts and cards must reconcile; if rounding individual cards creates a one-cent sum discrepancy, define and document a consistent display policy rather than use a broad tolerance.

Loss netting: subtract each carryover from its matching term, offset opposite signs against one another, then cap remaining capital-loss deduction at $3,000 ($1,500 MFS). Gains-only contributions can be zero while ordinary tax would remain positive; this is intentional, not a refund calculation.

## 5. Synthetic import fixtures

Prepare these later as valid exports in each supported brokerage format. Include acquisition/sale dates consistent with term where the format supplies them.

| Fixture | Contents | Required totals |
| --- | --- | --- |
| G0 | One valid zero-gain lot | ST 0, LT 0, total 0 |
| G1 | ST gain 10,000 and LT gain 20,000 | ST 10,000, LT 20,000, total 30,000 |
| G2 | ST gain 20,000 only | ST 20,000, LT 0 |
| G3 | LT gain 20,000 only | ST 0, LT 20,000 |
| G4 | ST loss −5,000 and LT gain 20,000 | Raw total 15,000; taxable net LT 15,000 |
| G5 | ST gain 20,000 and LT loss −5,000 | Raw total 15,000; taxable net ST 15,000 |
| G6 | ST loss −10,000 and LT loss −5,000 | Raw total −15,000; no taxable gains |
| G7 | Gains across two sources: A = G2, B = G3 | Combined ST 20,000, LT 20,000 |
| G8 | Multiple lots totaling ST 10,000.01 and LT 19,999.99 | Total exactly 30,000.00 |
| G9 | Identical-looking valid lots in one source | Both retained and included |
| G10 | Mixed 2025/2026 sales plus title/footer rows | Only selected-year valid lots included |

Add malformed file, unsupported headers, empty folder, missing directory, Unicode filenames, and a source filename containing HTML-like text. Include Schwab title rows and numeric zero versus blank/dash term columns. Fixture provenance and expected retained/rejected rows must be explicit.

## 6. California exact-dollar anchor cases — P0

All values are dollars. Year 2026, California, no carryovers or dependents unless specified. These are hand-derived planning-model targets, not executed results or full return liabilities.

| ID | Status | O before losses | Raw ST | Raw LT | Federal ST | Federal LT | California | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CA-01 | Single | 0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| CA-02 | Single | 50,000 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| CA-03 | Single | 0 | 20,000 | 0 | 390.00 | 0.00 | 175.09 | 565.09 |
| CA-04 | Single | 0 | 0 | 20,000 | 0.00 | 0.00 | 175.09 | 175.09 |
| CA-05 | Single | 50,000 | 10,000 | 20,000 | 1,200.00 | 2,167.50 | 2,155.45 | 5,522.95 |
| CA-06 | MFJ | 100,000 | 10,000 | 20,000 | 1,200.00 | 0.00 | 1,870.08 | 3,070.08 |
| CA-07 | Single | 50,000 | −5,000 | 20,000 | 0.00 | 0.00 | 934.88 | 934.88 |
| CA-08 | Single | 50,000 | 20,000 | −5,000 | 1,800.00 | 0.00 | 934.88 | 2,734.88 |
| CA-09 | Single | 50,000 | 10,000 | 20,000 | 0.00 | 0.00 | 300.00 | 300.00 |
| CA-10 | Single | 50,000 | −10,000 | −5,000 | 0.00 | 0.00 | 0.00 | 0.00 |
| CA-11 | MFS | 50,000 | −10,000 | −5,000 | 0.00 | 0.00 | 0.00 | 0.00 |

CA-09 alone uses ST carryover 15,000 and LT carryover 10,000: post-net taxable LT is 5,000. CA-10 ordinary income becomes 47,000; CA-11 becomes 48,500. Inspect formula income because the identical zero totals cannot establish correct loss-cap behavior.

Worked checks:

- CA-03: federal taxable ST = 3,900, taxed at 10%. California taxable income = 14,294; 11,079 × 1% + 3,215 × 2% = 175.09.
- CA-05: federal ordinary interval 33,900–43,900 gives 1,200; LT interval 43,900–63,900 gives (63,900 − 49,450) × 15% = 2,167.50. California interval 44,294–74,294 gives 13,248 × 6% + 15,182 × 8% + 1,570 × 9.3% = 2,155.45.
- CA-06: federal ordinary interval 67,800–77,800 gives 1,200; LT ends at 97,800, below the joint zero-rate ceiling. California interval 88,588–118,588 gives 26,496 × 6% + 3,504 × 8% = 1,870.08.
- CA-07: LT interval 33,900–48,900 remains at 0%; CA interval 44,294–59,294 gives 13,248 × 6% + 1,752 × 8% = 934.88.
- CA-09: CA interval 44,294–49,294 gives 5,000 × 6% = 300.00.

Before executing any anchor: have a second reviewer independently check the ledger. Keep one authoritative expected amount per cell and record any reviewed corrections.

For every anchor: load its fixture via the browser; select year/state/status; fill inputs; submit; verify raw dashboard totals, taxable intervals, every formula slice, tax cards, total, mapped rates, and credit disclosures. Open and close both dialogs. Reload and repeat the assertions against restored values.

## 7. Boundary and metamorphic cases — P0/P1

| ID | Procedure | Numerical acceptance |
| --- | --- | --- |
| NUM-01 | For every CA bracket in all five statuses, set closing taxable income to threshold −1, threshold, threshold +1 with positive imported gain | Independent slice sums; no whole-income multiplication by top rate; exact boundary maps to the band ending there |
| NUM-02 | Repeat federal ordinary boundaries and both preferential-gain thresholds for all statuses | Correct incremental tax and LT stacking; no overlap or missing dollar |
| NUM-03 | Set gross income to deduction −1, deduction, deduction +1; repeat with ST only, LT only, mixed terms | Taxable income floors at zero; deduction used once; unused deduction offsets LT |
| NUM-04 | Split the same total gain into many lots and across brokers; reorder files/rows | Identical totals and estimate; no per-lot tax rounding |
| NUM-05 | Change CA ST to LT with equal combined gains and fixed O | CA amount unchanged; federal may change |
| NUM-06 | Increase matching carryover from 0 through exact gain to gain +1; repeat opposite-term loss and both losses | Correct net term, no negative taxable gains, correct cap |
| NUM-07 | Use imported cents, half-cent tax products, large values | Reviewed rounding policy, no float artifacts, NaN, infinity, or scientific display |
| NUM-08 | Repeat a fixed profile under each filing status | Correct deduction/schedule; QSS matches joint brackets but federal credit phaseout status is independently checked |
| NUM-09 | Hold other inputs fixed, increase positive gains | No unexplained downward tax jump; rate transitions continuous |
| NUM-10 | California taxable income 999,999 / 1,000,000 / 1,000,001 and gains crossing that line | Ordinary-model result plus separate statutory surcharge comparison; missing surcharge must be explicitly disclosed or reported as a fidelity defect |

For NUM-10, choose single O = 1,005,706 and ST gain = 10,000: CA opening taxable income is 1,000,000, closing 1,010,000. Ordinary incremental tax is 1,230; surcharge increment is 100; fuller state result is 1,330 before other adjustments. Do not accept 1,230 as a complete California result without disclosure. The current code inspection does not establish surcharge support.

## 8. Federal and California dependent benefits — P0

| ID | Setup/action | Expected result |
| --- | --- | --- |
| DEP-01 | CA-05, set children 2 and other dependents 1 | Separate federal potential credit 4,900; gains tax unchanged; CA benefit informational, not an applied 475 × count credit |
| DEP-02 | Single, one child + one other; proxy MAGI 200,000 / 200,001 / 201,000 / 201,001 / 254,000 | Potential federal amounts 2,700 / 2,650 / 2,650 / 2,600 / 0; one combined phaseout |
| DEP-03 | Repeat DEP-02 MFJ around 400,000 using the same excesses | Same reductions above joint threshold |
| DEP-04 | Zero gains and low income, eligible children present | Gains tax 0; no negative total or refundable amount; potential credit clearly limited by total liability |
| DEP-05 | Change children from 1 to 2, then other dependents 0 to 1 | Potential changes by 2,200 then 500 below phaseout; no double-counting between categories |
| DEP-06 | Enter 0, 99, −1, 100, fractional and blank counts | Valid range/integer behavior; invalid input cannot leave an apparently current calculation |
| DEP-07 | Change carryovers with raw imported gains unchanged | MAGI proxy semantics explicitly checked and disclosed; distinguish current raw-gain proxy from actual AGI/MAGI after allowable losses |
| DEP-08 | California counts 0 versus positive at low/high income | No fabricated supported state credit; provisional source-year and unsupported phaseout visible |

Phaseout cases can use ST 1,000 and adjust O so O + raw ST + raw LT equals each target MAGI. Prepare a separate full tax ledger for each case; the amounts above validate the credit card only. Changing ordinary income must also update gain tax correctly.

The current MAGI helper uses ordinary input plus imported net gains, floored at zero, without carryover adjustment. Test and document that proxy separately from a tax-law oracle; a proxy mismatch must not be treated as proven statutory MAGI correctness. Qualified dividends included in the ordinary-income field likewise require scope disclosure, since preferential dividend treatment is not separately modeled.

Future California-credit support requires a new source-reviewed matrix for state eligibility, personal/dependent credit interaction, status-specific phaseout increments, thresholds, zero floors, and liability limits. Keep those cases marked deferred until requirements and inputs exist; do not invent formulas.

## 9. Browser update and concurrency behavior — P0

| ID | Browser actions | Acceptance |
| --- | --- | --- |
| UI-01 | Starting with CA-05, change state | All old output hidden immediately, including rates, credits, formula and payment actions; exact stale message appears |
| UI-02 | Change filing status | Same clearing behavior; no automatic display of mismatched old results |
| UI-03 | Click main Update estimate; repeat with inline bold Update estimate | Same request and resulting values; inline control keyboard-operable; message: “Estimate inputs changed. Click Update estimate to calculate with these values.” |
| UI-04 | Change each monetary field/count by typing and blur | Automatic recalculation; no button required; latest values displayed within bounded completion time |
| UI-05 | Type rapidly through several values | Only final input snapshot may settle; no older response overwrites it |
| UI-06 | Delay an ordinary-income response, then change state/status before it arrives | Delayed response cannot re-show output for old state/status; remain cleared until valid update |
| UI-07 | Queue a debounced input update, then immediately change status | Pending timer must not defeat the selection-clearing contract |
| UI-08 | Delay request A, submit B, release B then A | Only B rendered and persisted; verify after refresh, not just in DOM |
| UI-09 | Edit to invalid/empty input during an active request | Old result never presented as current; clear validation and recovery |
| UI-10 | Return 500, disconnect, or return HTML missing output | No false success, stale or error state visible; retry works |
| UI-11 | Open formula/rules after several asynchronous replacements | Correct current dialogs open once, close by button/Escape, no console errors or stale content |
| UI-12 | Two tabs use different profiles, then refresh | Defined persistence behavior; never silently combine one tab's profile with another tab's estimate |

For the immediate-update contract, old amounts should be hidden or visibly pending while waiting. A valid old amount displayed without qualification next to new inputs is a failure. Browser inspection suggests races around selection changes and in-flight requests deserve special attention; these are hypotheses, not executed findings.

## 10. Imports, navigation, persistence, and export — P0/P1

| ID | Browser journey | Acceptance |
| --- | --- | --- |
| FLOW-01 | Choose synthetic records root, explicit year, Load data | Correct year/source displayed; lot/security/source subtotals match independent ledger |
| FLOW-02 | Use auto-detect, year folder, source folder, direct CSV folder | Consistent documented selection; newest year only when auto-detect selected |
| FLOW-03 | Load G7; toggle A/B inclusion | Totals and tax match selected sources; final-source guard behaves; selection survives tax update and report creation |
| FLOW-04 | Change year while estimate/dialog present | No prior-year rates/results remain labeled as new year; missing annual state rules show unavailable, never silent fallback |
| FLOW-05 | Expand security to lots | Every included lot, term, gain and count matches fixture; duplicates retained intentionally |
| FLOW-06 | Reload, back/forward, new tab, restart app later | Year/profile/source persistence conforms to documented behavior; results always reconcile with visible inputs |
| FLOW-07 | Create Excel report and download | Correct filename/year; actual download; independently inspect totals/lots/source notes in workbook, not just HTTP success |
| FLOW-08 | Repeat report creation with existing report | Documented archive/replacement behavior; no input loss; latest included-source selection used |
| FLOW-09 | Malformed/empty/missing source and unavailable output directory | Actionable error, no stale successful dashboard masquerading as new load; recovery possible |
| FLOW-10 | Mixed broker G1 equivalents, Schwab blank/dash/zero cases | Identical normalized economics; correct term classification and source limitations |
| FLOW-11 | Inspect payment links and terms | IRS/FTB destinations match selected jurisdiction; no payment submission; never imply displayed amount is required installment |
| FLOW-12 | Load offline with local fixtures/rules | Core calculation works without external tax lookup; external links optional |

Report contents are auxiliary artifact assertions triggered by a real browser download. They may be inspected with an independent workbook reader later; this does not replace the browser workflow.

## 11. Layout, accessibility, and input validation — P1

1. At desktop widths confirm row one: State residence, Filing status, CTC-eligible children, Other credit-eligible dependents. Row two: Other ordinary taxable income ($), Short-term loss carryover ($), Long-term loss carryover ($), Update estimate. Four columns fill available row width; button does not occupy its own third row.
2. At responsive widths permit deliberate reflow; require no clipped labels, horizontal page overflow, unusable input widths, or detached button. Capture full panel screenshots at every breakpoint and zoom setting.
3. Open every tooltip individually and in combination, especially leftmost/rightmost fields. Entire explanation stays inside viewport/panel visibility; no clipping by overflow or obstruction by neighboring panels. Repeat after scroll and resize, using mouse, keyboard, and touch.
4. Currency fields have ($), accept the defined numeric format, and have no spinner arrows. Dependent counts retain working native spinner arrows where the browser supports them. Confirm min/max/step validation through actual interaction.
5. Test pasted commas/currency symbols, negative values, decimals, exponent notation, whitespace, letters, huge values, and temporarily empty text. Record accepted/rejected behavior explicitly. Current monetary controls use step=1; decide whether cents entry is a requirement before asserting that decimal input should pass. Imported cents must remain accurate regardless.
6. Check label associations, logical tab order, visible focus, tooltip accessible names, inline update semantics, stale status announcement, dialog focus containment and focus restoration. Hidden results must not remain announced as current.
7. Check formula table on small screens: scrollable data, readable sticky first column, dismissible modal. Do not accept a screenshot-only pass if keyboard controls fail.
8. Verify HTML-like fixture names render as text without executing markup. Browser network traffic must not send synthetic brokerage content to third parties during local calculation.

## 12. Non-California regression coverage — P1

- A state without individual income tax: verified zero state contribution, not a missing-rule error; federal result unchanged for identical profile.
- A state with an explicitly unsupported required calculation: state shows Unavailable, never a misleading $0; total communicates partial coverage.
- A supported state-dependent deduction: independent fixture shows taxable-state-income reduction and federal unchanged.
- A supported nonrefundable state credit: separate potential amount and liability cap; no accidental subtraction from gains-only total.
- A state with capital-gain exclusions or special treatment: choose from the current rule manifest at execution planning time and prepare source-reviewed expectations; do not assume ordinary California behavior applies.
- Blank state: federal remains coherent; state unavailable/selection message is clear; no California links/rules left behind.

## 13. Evidence and completion gates

For each executed case later, record ID, priority, fixture/hash, input snapshot, expected and actual values, difference, browser/viewport, screenshot, relevant response/input sequence, and pass/fail/blocked status. Capture console errors and traces on failure. Store only synthetic data.

Proposed sequence: independently review numerical ledger; smoke imports; California anchors; boundaries and credits; input transitions/races; export/persistence; responsive/accessibility; cross-browser and other-state regression.

Completion requires all P0 cases passing in the primary browser, critical California and input-transition cases passing cross-browser, all P1 cases completed or explicitly accepted, no unexplained numerical discrepancies, and clear disposition of provisional data/surcharge/table limitations. Unsupported cases must be labeled, not counted as passing calculations. No actual payment flow is executed.

Deliverables when execution is separately requested: reviewed fixture ledger, browser test implementation, run report, failure evidence, and tax-fidelity limitation register. This planning deliverable contains none of those execution results.
