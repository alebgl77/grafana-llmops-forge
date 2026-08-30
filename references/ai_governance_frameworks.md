# Governance frameworks — one telemetry layer, three readings

Verified 30 August 2026. Support for compliance evidence; **not a legal opinion
and not a certification**. Say so to the user, every time.

The three regimes a CIO is likely to be held to differ in vocabulary, in legal
force, and in what they oblige. They agree almost entirely on **what has to be
observable**. Build the runtime layer once and it pays into all three — which is
the whole argument of the governance dashboard.

`--framework eu-ai-act,iso-42001,nist-rmf` (the default) renders all three
readings; pass one to keep the board focused.

## 1. The crosswalk

| Observable signal | EU AI Act | ISO/IEC 42001:2023 | NIST AI RMF 1.0 |
|---|---|---|---|
| Logs exist continuously and are retained | Art. 12 · Art. 26(6) | A.6.2.8 | MANAGE 4.1 |
| Production systems are monitored | Art. 72 post-market | A.6.2.6 · Cl. 9.1 | MEASURE 3.x · MANAGE 4.1 |
| Inventory of models actually consumed | Art. 26 · GPAI chain | A.10 | GOVERN 6.1 · MAP 4.1 |
| Provider dependency and jurisdiction | GPAI contractual terms | A.10 | GOVERN 6.2 |
| Quality and drift measured | Art. 15 accuracy/robustness | A.6.2.6 | MEASURE 2.x |
| Incidents detected and escalated | Art. 73 | A.8 | MANAGE 4.x |
| Who uses the systems, and how | Art. 4 · Art. 26 | A.9 | GOVERN 1.x |

## 2. What each framework actually is

**EU AI Act** (Reg. (EU) 2024/1689) — binding law, extraterritorial, penalties up
to 35 M€ or 7 % of turnover. Obligations depend on your role (provider vs
deployer) and on risk class. Timeline and current status in
`eu_ai_act_observability.md`.

**ISO/IEC 42001:2023** — a certifiable AI management system standard, published
December 2023, international and sector-neutral. Certification audits clauses
4–10 plus the Annex A controls you declare applicable (38 controls, nine groups
A.2–A.10), in two stages, valid three years with annual surveillance. Stage 2 is
where documents stop being enough: A.6.2.6 (operation and monitoring) and
A.6.2.8 (event logs) want operational evidence.

> Annex A numbering varies between secondary sources. Confirm every reference
> against your own copy of the standard before it enters a Statement of
> Applicability — the text is paywalled and cannot be verified from here.

**NIST AI RMF 1.0** (NIST AI 100-1, January 2023) — voluntary, US de facto
reference, four functions (GOVERN, MAP, MEASURE, MANAGE) and roughly seventy
subcategories. NIST AI 600-1, the Generative AI Profile (July 2024), adds twelve
GenAI-specific risk categories mapped back to the same four functions.

## 3. What the dashboard proves, and what it does not

Proves: that logging is continuous, that a model inventory exists and matches
reality, which providers and jurisdictions you actually depend on, that quality
is measured, that incidents surface.

Does not prove: a management system exists (ISO clauses 4–10 are organisational
work no tool performs), that a risk assessment was done, that human oversight is
effective, that retention is configured — retention is a backend setting the
dashboard can only point at.

Be explicit with the user on both halves. A governance dashboard oversold is
worse than none: it invites a false sense of coverage in exactly the review
where that gets discovered.

## 4. Beyond these three

Colorado AI Act, California transparency rules, Korea's AI Framework Act,
Japan's soft-law approach, Brazil's PL 2338, China's GenAI measures — all
converge on the same observable primitives (inventory, logging, monitoring,
incident handling). Adding one is a row in the crosswalk table and a markdown
panel in `FRAMEWORKS`, not new instrumentation.
