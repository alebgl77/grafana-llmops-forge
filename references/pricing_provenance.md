# Provenance des prix tiers

Le registre livré reste la source hors ligne et ne contient aucune valeur
Artificial Analysis. Le fallback tiers est désactivé par défaut.

## Activation et secret

L'activation exige les deux éléments suivants:

```bash
export ARTIFICIAL_ANALYSIS_API_KEY="..."
python3 scripts/forge_dashboards.py --capability capability_map.json \
  --pricing-fallback artificial-analysis
```

La forge n'accepte aucun autre nom de variable ou argument de clé. La valeur
sert uniquement à l'en-tête `x-api-key`; elle n'est ni affichée, ni placée dans
une URL, ni écrite dans un fichier.

## Requête et dégradation

La seule API appelée est `GET
https://artificialanalysis.ai/api/v2/language/models/free`, avec `page=N` pour
la pagination. Les délais, pages, modèles et octets sont bornés. Une redirection
vers une autre origine est refusée. Aucun appel n'a lieu si tous les modèles
détectés ont déjà un tarif complet ou si un cache frais les couvre.

Un modèle n'est accepté que si sa valeur observée correspond exactement, après
normalisation alphanumérique en minuscules, à un unique `id`, `slug`, `name` ou
alias. Une ambiguïté, une absence, un prix input/output null, un JSON invalide,
un HTTP 401, 403, 429 ou 5xx laisse le modèle non tarifé. La forge continue.

## Sémantique et cache

Les valeurs retenues sont des estimations médianes multi-provider. Chaque
entrée porte `pricing_source_kind: artificial_analysis`, l'URL source, un
horodatage ISO UTC, `pricing_basis: median_multi_provider`, `estimate: true` et
l'attribution `Artificial Analysis`. Un tarif officiel complet reste
prioritaire.

L'overlay `model_registry.artificial-analysis.cache.json` est écrit atomiquement
près de la capability map et est frais 24 heures par défaut. Il contient
uniquement les entrées AA retenues, leur provenance et l'empreinte du registre
officiel utilisé comme base, jamais le registre fusionné. La base est toujours
`--registry`, un éventuel `model_registry.local.json` officiel, ou le seed
livré. La durée est ajustable avec `--pricing-cache-max-age-hours`. Un overlay
expiré, falsifié, ambigu, lié à une autre base ou illisible est ignoré entrée
par entrée sans arrêter la forge. Cet overlay est exclu du paquet `.skill` et
du SBOM; seules les sources du mécanisme sont distribuées.
