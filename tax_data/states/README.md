# State tax reference data

These files are deterministic planning data for tax year 2026. They are not a
complete state-return engine and must not be used to file a return without
checking the final state instructions.

## Conventions

- One file lives at `<lowercase postal abbreviation>/2026.yaml` for every
  jurisdiction in `2026-manifest.yaml`.
- `bracket` is the inclusive upper bound of a marginal band. The final band is
  open-ended and therefore uses `bracket: null`.
- Rates are percentages, so `4.95` means 4.95%, not 0.0495.
- The five federal-style filing-status keys are always present for ordinary
  schedules. A state-specific status mapping is documented in `filing_status_notes`.
- `data_status.status: final` means the cited state source publishes the 2026
  parameter. `provisional` means at least one named field still uses the latest
  published prior-year amount or a statutory value that can change later.
- `calculation_supported: false` flags a formula, recapture, phaseout, special
  table, or unpublished value that a simple bracket calculator cannot safely
  compute from this file alone.
- Each `dependent_benefits` entry has an explicit `benefit_type`, eligibility
  basis, income measure, calculation method, phaseout support flag, source
  year/source reference, publication status, and calculation support decision.
  A dollar amount is informational unless `calculation_supported: true`.
  Supported deductions require a separately confirmed state-eligible-dependent
  count; federal CTC/ODC counts are never silently reused. Nonrefundable
  credits are shown separately from the gains-only estimate, and refundable
  credits are never subtracted from it.
- `capital_gains` explicitly records whether gains use the ordinary schedule,
  a separate rate, an exclusion/deduction, or no broad state tax. Short-term
  gains use the ordinary schedule unless a note says otherwise.
- Credits are limited to broadly applicable dependent, child, and earned-income
  provisions. Specialty credits and full eligibility tests are out of scope.
- County, city, school-district, and other local income taxes are excluded.
- Washington is included only for its tax on net long-term capital gains; it
  does not impose a broad individual income tax in 2026.

Every file embeds authoritative state-agency or state-code URLs. Its top-level
`filing.payment_url` is the official payment destination; it is intentionally
separate from `sources`, which documents tax-rule evidence. `2026-manifest.yaml`
is the coverage and publication-status index.

## Adding a dependent benefit

Add a benefit only to the jurisdiction's annual YAML and give it a stable `id`.
Declare its `benefit_type`, `eligibility_basis`, `income_measure`, allowed filing
statuses, calculation method and amount, phaseout support, refundability,
tax-liability limit, source year, authoritative source key, and publication
status. Set `calculation_supported: true` only when the complete formula and
every required app input are represented. Otherwise supply an
`unsupported_reason`; the dashboard will keep it informational instead of
silently applying it. Add or update the state-data and benefit-calculation
tests for every newly supported formula.
