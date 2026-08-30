# Show HN : texte final, prêt à coller

Fenêtre : mardi ou mercredi, 15h00-17h00 CET (= 9h-11h ET, pic de trafic HN).
Soumission : https://news.ycombinator.com/submit

## Titre (A par défaut)

A. `Show HN: Point it at any Grafana, get LLM FinOps and EU AI Act dashboards`
B. `Show HN: A dashboard generator that runs every query it writes against a real Prometheus`

A vend le résultat, B vend la méthode. A pour le volume, B pour les commentaires d'ingénieurs. Pas de majuscules criardes, pas de point d'exclamation.

## URL

https://github.com/alebgl77/grafana-llmops-forge

## Premier commentaire, à poster immédiatement après la soumission

Sans lui, le post part sans contexte et meurt. Coller tel quel :

```
Author here.

The itch: every "LLM observability dashboard" I found was static JSON that
assumed metric names. But OTel exporters disagree on suffixes, LiteLLM speaks
USD natively while OTel gives you raw token counters, and vLLM has its own
prefix entirely. Import someone else's dashboard and half the panels say
No data.

So this isn't a template pack, it's a generator. It probes your Grafana's
datasources first, captures the metric names that actually exist, and only
emits panels whose queries will return something. No signals at all is a
valid outcome: you get an instrumentation gap report with exact configs
instead of a wall of empty graphs.

Two bugs it found in itself are more interesting than the feature list, and
each one taught me which layer of testing was missing.

1. It billed a model at 5.5x the wrong price. Cost is composed by matching
   observed model names against a price registry. The first version used
   substring matching, so "gpt-5.4-mini" matched "gpt-5.4" and got billed at
   the big model's rate. Nobody would have noticed: the dashboard would just
   have been confidently wrong, forever. An offline harness that renders the
   blueprints against four simulated instance topologies caught it. Fixed
   with a specificity scorer; there's a regression test.

2. Then a bug that harness structurally could not catch. PromQL label
   matchers are quoted strings, so a regex inside one gets unescaped twice:
   Python's re.escape emits a backslash-hyphen, which RE2 rejects outright,
   and a single backslash-dot is eaten by the string literal before the regex
   engine ever sees it. The generated JSON was perfectly valid. The queries
   looked syntactically plausible. They just errored at query time. The panel
   affected was the sovereignty split on the EU AI Act board (the one thing
   you would put in front of an auditor), and it was broken for every model
   name containing a hyphen or a dot, which is nearly all of them.

   The fix wasn't the escaping, it was the missing test class. The repo now
   downloads a real Prometheus, feeds it a synthetic LLM workload, runs the
   whole pipeline and executes every generated expression against real data.
   63 of 63 return data, and that's a CI job. Structure is not semantics, and
   I had been testing only structure.

That principle got generalised: after deploying, it screenshots every panel
(native Grafana renderer, headless browser fallback) and does a vision pass
looking for No data panels, impossible values like p50 above p95, and
cross-panel incoherence such as tokens/s above zero while cost sits at zero,
which means a model didn't match the registry. HTTP 200 means the JSON was
accepted, not that the render is right.

Other things people might care about. Zero dependencies, stdlib only, about
2500 lines, deliberately readable in one sitting given that a Snyk audit this
year found roughly a third of published agent skills had at least one flaw.
Cost scales through generated Prometheus recording rules, so prices become
series and the FinOps panels collapse to one O(1) query instead of a 2N-term
sum; those rules also ship as a PrometheusRule manifest, because most enterprise
clusters run the Prometheus Operator and will not read a flat rule file.

The governance board reads the same telemetry against the EU AI Act, ISO/IEC
42001 and NIST AI RMF, selected with --framework. That is less clever than it
sounds: the frameworks differ in vocabulary and legal force but agree almost
entirely on what has to be observable, so the same log volume evidences Art. 12,
A.6.2.8 and MANAGE 4.1. The measured panels are identical either way. The board
also states what it does not prove (a management system, a risk assessment,
effective human oversight), because a governance dashboard oversold is worse
than none.

Dashboards render in English by default, French with --locale; adding a language
is a JSON file rather than a change to any blueprint. It works as a plain CLI or
as an agent skill.

make demo boots Grafana, Prometheus and a synthetic workload and deploys the
whole thing in about a minute if you want to poke at it before reading code.

Happy to go into the PromQL composition, the AI Act article-to-signal
mapping, or why the README diagrams are hand-drawn SVGs explicitly labelled
as illustrations rather than fake screenshots.
```

## Réponses pré-écrites

**« Grafana Cloud ships AI Observability already »** : la question la plus probable
> Yes, and it's good: Agent Observability went public preview in April 2026. Two differences that matter for who I built this for: it's Cloud-only, and it asks you to adopt their SDK. This runs on self-hosted OSS against whatever you already emit. It also does two things no vendor ships: cost attribution by provider sovereignty, which EU procurement teams are actively asking for, and an AI Act evidence layer. They compose fine; nothing here conflicts with the Grafana plugins.

**« Why not Langfuse / Helicone / Arize? »**
> Different layer. Those are platforms you adopt instead of what you have. This assumes you already run Grafana, which most platform teams do, and turns it into the AI surface. No new tool, no new login, no new vendor security review.

**« Does it phone home? »**
> No. It talks to your Grafana, which talks to your own Prometheus/Loki/Tempo. No telemetry, no third-party calls, except an optional price-registry refresh you can skip.

**« Is the AI Act part legal advice? »**
> No, and the dashboard says so on itself. It is the evidence layer your counsel will ask for: logging continuity, retention posture, an auto-built inventory of the models you actually consume, and incident watch.

**« Prompt contents in telemetry? »**
> Off by default, and the docs treat turning it on as a GDPR decision rather than a flag.

**« License, cost? »** MIT, free, no hosted tier, no upsell inside the tool.

## Après publication

- Répondre sous 30 minutes pendant trois heures : c'est la fenêtre où HN décide si ça monte.
- Si un commentaire trouve un vrai bug : corriger en direct, pousser, répondre avec le lien du commit. Rien ne convainc autant sur HN.
- Ne pas cross-poster sur Reddit le même jour. Laisser 24 à 48 h (voir LAUNCH_PLAYBOOK).
- Si le post ne décolle pas : ne pas le resoumettre. Enchaîner sur r/grafana avec l'angle « générateur qui ne crée que des panels que vos métriques peuvent réellement alimenter ».
