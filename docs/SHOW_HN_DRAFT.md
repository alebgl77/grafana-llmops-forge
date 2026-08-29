# Show HN — prêt à coller

Publier : mardi ou mercredi, 15h00-17h00 CET (= 9h-11h ET, fenêtre de trafic HN la plus dense).
URL : https://news.ycombinator.com/submit

## Titre (choisir A ou B, A par défaut)

A. `Show HN: Point it at any Grafana, get LLM FinOps + EU AI Act dashboards`
B. `Show HN: I turned Grafana into an AI observability suite that verifies its own dashboards`

Règles HN : pas de majuscules criardes, pas de "!", rester factuel — les deux respectent ça.

## URL soumise
https://github.com/alebgl77/grafana-llmops-forge

## Premier commentaire (à poster IMMÉDIATEMENT après soumission, sinon le post part sans contexte)

```
Hi HN, author here.

The trigger: I kept seeing "LLM observability" dashboards that were really
just static JSON assuming metric names that don't match what your actual
OTel/LiteLLM/vLLM exporter emits. So this is a forge, not a template pack —
it probes your Grafana's real datasources first, captures the metric names
that are actually present, and only generates panels that will return data.

Three things I think are worth a look even if you don't run Grafana:

1. It found its own billing bug. The cost-composition engine matches
   observed model names against a price registry. First version used
   substring matching — "gpt-5.4-mini" matched "gpt-5.4" and got billed at
   5.5x the wrong price. An offline audit harness (4 simulated instance
   topologies, 27 checks) caught it before anyone's dashboard would've lied
   to them. Fixed with a specificity scorer, regression-tested.

2. Zero dependencies, on purpose. A Snyk audit of published Claude skills
   this year found ~36% had at least one security flaw. This is stdlib-only
   Python (~2000 lines) specifically so it can be read in one sitting.
   Playwright is opt-in, only for the visual-audit fallback.

3. It checks its own rendering. API 200 means the JSON was accepted, not
   that the panel renders sensibly. After deploy it captures every panel
   (native Grafana renderer or a headless browser) and an AI vision pass
   checks for "No data" panels, impossible values (p50 > p95), and
   cross-panel coherence (tokens/s > 0 but cost = 0 → model didn't match
   the registry) — then loops remediation before calling it done.

It works as a plain 3-command CLI or as a Claude Agent Skill (open
agentskills.io standard). Happy to answer anything about the PromQL
composition, the EU AI Act mapping, or why I didn't just use LLM-generated
images for the README (spoiler: hand-built SVGs, dark-mode native, felt
more honest for a dev tool).
```

## Réponses pré-écrites pour les questions attendues

**"Why not [Langfuse/Helicone/Arize]?"**
> Different layer. Those are LLM-specific observability platforms you adopt instead of what you have. This assumes you already run Grafana (most platform teams do) and turns it into the AI observability surface — no new tool, no new login, no new vendor relationship for the security review.

**"Does this send data anywhere?"**
> No. It talks only to your Grafana instance (which talks to your own Prometheus/Loki/Tempo). No telemetry, no phone-home, no third-party API calls except the optional price-registry refresh (a plain web search you can skip).

**"Grafana Cloud rate limits?"**
> One API call per dashboard on deploy; visual audit does one render call per panel. Negligible even on free tier.

**"License?"**
> MIT.

## Après publication

- Répondre à chaque commentaire < 30 min pendant les 3 premières heures (fenêtre où HN décide si ça monte).
- Si un commentaire trouve un vrai bug : le corriger en live, pousser, répondre avec le lien du commit. HN adore ça, c'est plus fort que n'importe quel argument marketing.
- Ne PAS poster sur r/grafana etc. le même jour — laisser HN respirer 24-48h avant les autres canaux (évite l'air de spam cross-posté, cf. playbook).
