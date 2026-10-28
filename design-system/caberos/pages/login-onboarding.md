# Page: Login + Onboarding

> **Routes:** `/login`, first-run onboarding
> **Overrides:** `design-system/caberos/MASTER.md`

## Login

Centered column on `--ground`: `LogoMark` (`logo-land` spin-in) → "CaberOS"
wordmark → `rise-in` card (`max-w-sm`) — username/password `Input`s +
primary submit. Error → `danger` text. Boot handoff: `screen-in` fades the
app in after auth.

## Onboarding stepper

Stage-boundary fades (`stage-fade`); step-to-step horizontal slides —
`ob-step-in/out-fwd/back`, direction-aware on Back. `max-w-*` centered cards.

Steps (per `components/onboarding/`): welcome → operator account → provider
key → model pick → ready.

- **Provider step:** key `Input` + **Test connection** — helper text explains
  it sends one tiny request to prove the key works (cheapest tool-capable
  model, recorded as a probe call in the model ledger).
- **Ready step:** summary + tour offer (`PageIntro`/`TourSpotlight` hooks).

## Rules

- No page-level transitions in the app — screen-in/ob-step-* animations are
  scoped to auth + onboarding only.
- Everything honors `prefers-reduced-motion`.
