# Dependent-benefit browser test results

Run timestamp: 2026-09-23 19:34:05 PDT

Status: **DEP-01 through DEP-08 executed in the primary in-app browser. All executed acceptance checks passed; California dependent benefits remain informational as required by the current unsupported rule data.**

## Environment and provenance

- Repository commit: `676551b5e3b38605e7f33a074e4a4d56c23bb9ab`
- Browser: Codex in-app Browser
- Server: `http://127.0.0.1:8876`
- Viewport: default 1280×720
- Page locale: `en`; timezone: `America/Los_Angeles`
- Synthetic records root: `/private/tmp/capital_gain_e2e_20260923`
- No personal brokerage files or payment submissions were used
- Console errors during the final DEP-01 evidence capture: none

Rule and fixture hashes:

| Item | SHA-256 |
| --- | --- |
| `doc/IN_BROWSER_END_TO_END_TEST_PLAN.md` | `d53328c8c31b73d61f6316d1fe1ca0f32a3f7458df900a0bc13a3f61b20aa6a6` |
| `tax_data/federal/2026.yaml` | `902b5ae27636e56d2ad44f025f6e68dedb7496ac8973f60982eb1acd8c3fc14a` |
| `tax_data/states/ca/2026.yaml` | `66b111ea6b1f157df857b9e84c1c7bf3c72b0474b2b9664be5a5f8b17a0b3018` |
| DEP phaseout fixture `dependents-phaseout/source/phaseout.csv` | `bef8c858a0da9d7ca7de43cef46e47f571d46c7b3401f9caa35e9f8c97fd4a36` |
| CA-05 short-term fixture `records/2026/source/html-like-<script>.csv` | `9533e7da298f7750abaef9f241546cc85401c7c81fbe132d8094feec4bd400c5` |
| CA-05 long-term fixture `records/2026/source/Fidelity-long-term.csv` | `f7b4e15010dedf41e9d6a130514b6421957d95085f87a143a0c41cdaba1d21ff` |
| G0 fixture `records/2026/source/G0-zero.csv` | `7bb8c46e4513876c39650bc2564f9913ac95ae20df890faa3186a556d6c7c46d` |

## Results

### DEP-01 — CA-05 with 2 children and 1 other dependent

PASS.

- Raw gains: short-term `$10,000.00`, long-term `$20,000.00`.
- Federal potential credit: `$4,900.00` shown separately.
- Gains-only tax unchanged at `$5,522.95`.
- California dependent benefit was explicitly labeled informational and not applied as `475 × count`.

### DEP-02 — Single phaseout matrix

PASS. The synthetic fixture had short-term gain `$1,000.00`; ordinary income was adjusted so the displayed proxy MAGI hit each target.

| Proxy MAGI | Expected potential credit | Actual credit | Result |
| ---: | ---: | ---: | --- |
| $200,000 | $2,700 | $2,700 | PASS |
| $200,001 | $2,650 | $2,650 | PASS |
| $201,000 | $2,650 | $2,650 | PASS |
| $201,001 | $2,600 | $2,600 | PASS |
| $254,000 | $0 | $0 | PASS |

The UI disclosed the derived planning MAGI and phaseout reductions. The credit was not subtracted from the gains-only tax estimate.

### DEP-03 — MFJ phaseout matrix

PASS. The same reductions were observed at the joint threshold and target MAGIs `$400,000`, `$400,001`, `$401,000`, `$401,001`, and `$454,000`: `$2,700`, `$2,650`, `$2,650`, `$2,600`, and `$0`.

### DEP-04 — Zero gains and low income

PASS.

- Zero-gain fixture with 2 children and 1 other dependent produced federal estimate `$0.00`, state estimate `$0.00`, and total `$0.00`.
- The potential `$4,900.00` credit remained a separate nonrefundable estimate; the UI disclosed that total liability can limit it.
- No negative or refundable gains-only total appeared.

### DEP-05 — Dependent-category changes

PASS. With the CA-05 profile below phaseout:

| Children | Other dependents | Potential credit | Difference |
| ---: | ---: | ---: | ---: |
| 1 | 0 | $2,200 | baseline |
| 2 | 0 | $4,400 | +$2,200 |
| 2 | 1 | $4,900 | +$500 |

Gains-only tax stayed `$5,522.95` for all three states. No double-counting was observed.

### DEP-06 — Count validation

PASS. Native number-input validation behaved as follows for CTC-eligible children:

| Input | Browser result |
| ---: | --- |
| `0` | Valid |
| `99` | Valid |
| `-1` | Invalid; minimum is 0 |
| `100` | Invalid; maximum is 99 |
| `1.5` | Invalid; step is 1 |
| blank | Valid after actual select-all/backspace keyboard interaction |

The field was restored to a valid value after the checks. The initial automation `fill("")` did not clear an invalid number value, so the blank case was rerun with real keyboard clearing before being marked passed.

### DEP-07 — Carryover changes and MAGI proxy

PASS.

- Same CA-05 raw gains and dependents were used with carryovers `0/0` and `5,000/10,000`.
- Derived planning MAGI stayed `$80,000.00` in both cases because the current helper uses ordinary input plus imported raw net gains and does not subtract carryovers.
- Gains-only tax changed from `$5,522.95` to `$1,535.04`.
- The UI disclosed the value as a derived planning MAGI and separately disclosed that the credit is nonrefundable and not deducted from the gains-only estimate.

This validates the current proxy semantics, not statutory MAGI correctness.

### DEP-08 — California dependent benefits at low and high income

PASS as an unsupported/informational case.

- Low-income zero-gain profile with counts 0 and counts 2/1 both showed state estimate `$0.00`, with no applied `$475.00` amount.
- High-income CA-05 profile with ordinary income `$1,000,000` and counts 2/1 showed state estimate `$1,845.00`; the California dependent benefit remained informational, provisional, and unapplied.
- The dashboard consistently disclosed that eligibility, income limits, phaseout, age, residency, and current-year formula support are incomplete.

## Evidence

- [DEP-01 screenshot](/Users/decai/Desktop/My Apps/Capital-Gain-Estimate-Tax-Calculator/doc/test_results/20260923_193405_dep01.png)

The prior timestamped report contains the shared CA-05/fixture setup and primary browser evidence: [20260923_184534 results](/Users/decai/Desktop/My Apps/Capital-Gain-Estimate-Tax-Calculator/doc/test_results/20260923_184534_in_browser_e2e_test_results.md).

No implementation changes were made. The local server and all fixtures were disposable synthetic test artifacts.
