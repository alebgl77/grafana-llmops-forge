---
name: grafana-llmops-forge
description: Pilote l'observabilité IA/LLM de bout en bout sur Grafana (OSS, Cloud, Enterprise) avec un seul prérequis — une instance Grafana accessible. Auto-découverte (version, APIs, datasources), détection des signaux LLM présents (OTel GenAI gen_ai.*, LiteLLM, vLLM, TGI, GPU/DCGM), génération et déploiement automatiques de dashboards — FinOps & coûts multi-providers (US/EU/Asie), gateway, tracing agents & RAG, adoption interne, gouvernance EU AI Act, inference self-hosted — alerting SLO, registre de modèles avec pricing, puis contrôle visuel du rendu réel (captures renderer/navigateur inspectées par vision). Utilise ce skill dès que l'utilisateur mentionne Grafana, un dashboard, du monitoring/observabilité IA ou LLM, des coûts de tokens, du FinOps IA, du LLMOps, des agents ou du RAG, l'adoption de modèles, la conformité AI Act, ou Prometheus/Loki/Tempo appliqués à l'IA — même sans le mot « dashboard ». Vaut aussi pour auditer un Grafana existant ou une stack IA qui n'émet encore rien.
---

# Grafana LLMOps Forge

Transforme n'importe quelle instance Grafana en centre de commandement IA/LLM pour une DSI : découverte, génération de dashboards, alerting, FinOps, gouvernance AI Act. Prérequis unique : `GRAFANA_URL` + un token de service account. Tout le reste est découvert ou provisionné.

## Doctrine (ce qui rend ce skill différent)

1. **Discovery-first, jamais d'hypothèse.** On ne génère jamais un panel « au cas où ». On sonde l'instance et les datasources, on capture les **noms réels** des métriques présentes, et on ne construit que des panels dont les requêtes retourneront des données. Les exporters OTel varient dans leurs suffixes (`_seconds`, `_token`, `_total`) : c'est la capability map qui fait foi, pas la théorie.
2. **Quatre dialectes de télémétrie, un seul modèle mental.** Les signaux LLM arrivent en pratique sous 4 formes : conventions OTel GenAI (`gen_ai_*` — statut Development, v1.4x, opt-in `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`), passerelle LiteLLM (`litellm_*`, spend en USD natif), moteurs d'inference (`vllm:*`, `tgi_*`, `ollama_*`), et GPU (`DCGM_*`). Le générateur traduit chaque blueprint dans le dialecte détecté.
3. **Le coût est calculé, pas espéré.** Quand la passerelle expose le spend (LiteLLM), on l'utilise. Sinon, le générateur **compose des expressions PromQL** en joignant les compteurs de tokens au registre de modèles embarqué (prix input/output/cache par modèle, US/EU/Asie). Le registre porte une date de vérification ; s'il a plus de 30 jours et que la recherche web est disponible, rafraîchir les prix depuis les pages officielles AVANT de générer les panels de coûts (protocole dans `references/model_registry.json`, clé `_meta.refresh_protocol`).
4. **La gouvernance est observable.** L'AI Act impose journalisation (Art. 12), conservation des logs ≥ 6 mois côté déployeur (Art. 26§6), signalement d'incidents (Art. 73), transparence (Art. 50). Le dashboard gouvernance mappe articles → signaux mesurables, avec le calendrier vérifié post-Digital Omnibus (juillet 2026). Ce n'est pas un avis juridique : le dire explicitement à l'utilisateur.
5. **Idempotence totale.** UIDs déterministes (hash du nom), upsert avec overwrite, folder unique « AI Observability ». Relancer la forge est toujours sûr. Mode `--dry-run` disponible pour tout ce qui écrit.
6. **Dégradation élégante.** Zéro signal LLM détecté ≠ échec : produire un **rapport d'écart d'instrumentation** (quoi brancher, dans quel ordre, avec les configs exactes de `references/instrumentation_guide.md`) + déployer quand même le dashboard gouvernance (fonctionne sans métriques) et le squelette des autres avec annotation « en attente de signaux ».
7. **Vérifié par l'œil, pas seulement par l'API.** Un HTTP 200 prouve que le JSON est accepté, pas que le rendu est juste. Aux moments stratégiques (post-déploiement, remise du dashboard governance, gap comblé), capturer le rendu réel (`visual_audit.py` : renderer natif Grafana, fallback navigateur Playwright) puis **inspecter les PNG par vision** avec la checklist de `references/visual_verification.md` — plausibilité des échelles ($, latences), panels « No data », cohérence inter-panels — et boucler la remédiation (max 2 itérations). Ne jamais annoncer un déploiement réussi sans verdict visuel quand la capture est possible.

## Pipeline standard

Suivre ces phases dans l'ordre. Chaque script s'exécute avec Python 3 stdlib uniquement (aucun `pip install`).

### Phase 0 — Credentials

Variables d'environnement attendues :

```bash
export GRAFANA_URL="https://grafana.exemple.com"     # sans slash final
export GRAFANA_TOKEN="glsa_..."                       # token de service account
# Fallback accepté : GRAFANA_USER + GRAFANA_PASSWORD (basic auth)
```

Si l'utilisateur n'a pas de token : Administration → Users and access → Service accounts → créer un compte rôle **Editor** (Admin si provisioning d'alertes/datasources souhaité) → Add service account token. Sur Grafana Cloud, l'URL est `https://<stack>.grafana.net`. Ne jamais afficher le token en clair dans les réponses ni dans les fichiers générés.

### Phase 1 — Découverte

```bash
python3 scripts/discover.py --out capability_map.json
```

Produit la capability map : version/édition/namespace, disponibilité des APIs (legacy `/api` vs resource `/apis/dashboard.grafana.app`), datasources classées (prometheus-like, loki, tempo), dialectes LLM détectés **avec les noms réels de métriques**, labels Loki, et la liste des gaps. Lire le JSON et **résumer à l'utilisateur ce qui a été trouvé avant de continuer** — c'est le moment de corriger le tir (mauvaise datasource, instance de staging, etc.).

### Phase 2 — Registre de modèles

Lire `references/model_registry.json`. Si `_meta.verified_at` date de plus de 30 jours ET que la recherche web est disponible : rafraîchir les prix des modèles effectivement détectés dans la capability map (pas tout le registre) depuis les URLs de `_meta.sources`, puis écrire un `model_registry.local.json` à côté de la capability map. Le générateur charge le fichier local en priorité. Sans accès web : utiliser le seed tel quel — les dashboards de coûts affichent la date du registre dans leur description.

### Phase 3 — Sélection des blueprints

Six blueprints. Choisir selon la demande + la capability map (ne pas demander à l'utilisateur de re-choisir ce qu'il a déjà exprimé) :

| Blueprint | ID | Condition d'activation |
|---|---|---|
| Executive FinOps & Coûts | `finops` | tokens ou spend détectés (otel/litellm) |
| Gateway Operations (latence, erreurs, TTFT) | `gateway` | otel ou litellm |
| Agents & RAG (traces, tools, workflows) | `agents` | otel + Tempo idéalement ; otel seul = version métriques |
| Adoption interne (équipes, apps, mix modèles) | `adoption` | otel ou litellm |
| Inference self-hosted (vLLM/TGI + GPU) | `inference` | vllm/tgi/ollama ou DCGM détectés |
| Gouvernance EU AI Act | `governance` | toujours activable (fonctionne dégradé) |

### Phase 4 — Forge et déploiement

```bash
# Tout ce qui est activable :
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints auto --deploy --with-alerts
# Ou ciblé :
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints finops,governance --deploy
# Vérification sans écriture :
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints auto --dry-run
```

Le script génère les JSON (schéma classique v41 — compatible OSS/Cloud/Enterprise de la v9 à la v13, déployé via l'API legacy, fallback API resource K8s-style si nécessaire), crée le folder, upsert les dashboards, provisionne les alertes SLO (`--with-alerts` : taux d'erreur burn-rate, TTFT p95, budget quotidien, saturation KV cache, absence de signal), écrit `deploy_manifest.json` puis imprime les URLs. Toujours relayer les URLs finales à l'utilisateur.

### Phase 4b — Contrôle visuel (vision) — obligatoire après tout déploiement

```bash
python3 scripts/visual_audit.py --dashboards generated_dashboards --out visual_audit
```

Sélection auto du moteur : `/render/...` natif Grafana (plugin image-renderer ; inclus sur Cloud), sinon Playwright (vrai navigateur headless, auth par header Bearer, mode kiosk, pré-scan DOM des « No data »/erreurs). Ensuite **ouvrir les PNG par vision** (`visual_audit/<dash>/full.png` d'abord, panels douteux ensuite, correspondances dans `audit_manifest.json`) et appliquer la checklist + la table signatures→correctifs de `references/visual_verification.md`. Verdict par dashboard (✅/⚠/❌), remédiation à la source (registre, capability map, code — jamais l'UI), re-forge, re-capture des seuls dashboards corrigés, max 2 itérations. Le même script vérifie des paramétrages hors dashboards (datasources, règles d'alerte) via Playwright — voir la référence §6.

### Phase 5 — Rapport d'écart

Si des blueprints demandés sont bloqués par des signaux manquants : lire `references/instrumentation_guide.md` et produire un plan d'instrumentation ordonné par ratio valeur/effort (typiquement : 1. LiteLLM devant les providers → spend immédiat ; 2. OTel GenAI dans les apps → traces agents ; 3. DCGM si GPU on-prem). Donner les configs exactes, pas des généralités.

### Phase 6 — Restitution

Format de sortie systématique : ce qui a été **détecté** → ce qui a été **déployé** (URLs) → ce qui **manque** et comment le combler → prochaines étapes datées si gouvernance activée (échéances AI Act). Concision : une DSI lit ça en 90 secondes.

## Personnalisation au-delà des blueprints

Les scripts couvrent le noyau déterministe. Pour étendre (panels supplémentaires, requêtes spécifiques, variables custom) :
- `references/query_library.md` — bibliothèque PromQL/LogQL/TraceQL par dialecte, prête à coller dans de nouveaux panels.
- `references/dashboard_blueprints.md` — spécification panel par panel des 6 blueprints, y compris les panels optionnels non générés par défaut.
- `references/grafana_api_compat.md` — matrice OSS/Cloud/Enterprise, APIs legacy vs resource, namespaces Cloud (`stacks-<id>`), schéma v2 (dynamic dashboards) et quand l'utiliser.
- Pour ajouter un panel à un dashboard déjà déployé : re-générer avec la forge (source de vérité = le code), jamais d'édition manuelle silencieuse — sinon la prochaine exécution écrase.

## Pièges connus

- **Suffixes OTel→Prometheus variables** : `gen_ai.client.token.usage` peut apparaître comme `gen_ai_client_token_usage_token_*`, `..._tokens_*` ou sans unité selon l'exporter. Le résolveur de la forge matche par préfixe sur les noms capturés en Phase 1 ; ne jamais coder un nom en dur sans vérifier la capability map.
- **Cardinalité** : ne jamais grouper par `gen_ai.conversation.id` ou tout ID unique dans un panel de série temporelle. Les approximations d'« utilisateurs actifs » passent par `count(count by(label)(...))` sur un label borné.
- **Prix par paliers** : certains modèles (ex. Gemini 3.1 Pro) changent de prix au-delà d'un seuil de contexte ; le registre porte `tiered_pricing` et le panel de coût affiche alors une note « estimation basse ».
- **Grafana Cloud** : l'API legacy dashboards fonctionne, mais les alertes provisionnées exigent le bon `folderUID` et un token avec rôle suffisant ; en cas de 403, dégrader en exportant les règles en JSON et indiquer l'import manuel.
- **Contenu des prompts** : ne jamais encourager la capture de `gen_ai.input.messages`/`output.messages` par défaut (données sensibles). Si l'utilisateur la veut : opt-in explicite + renvoyer aux précautions de `instrumentation_guide.md`.
- **Rendu absent** : `/render/...` en 404 = plugin grafana-image-renderer non installé (installation en une ligne dans `visual_verification.md` §5) ; basculer sur `--engine playwright` en attendant. Derrière un SSO/proxy où le Bearer ne passe pas : `GRAFANA_COOKIE`.
- **Captures sensibles** : les PNG d'audit contiennent coûts, équipes, modèles — stockage local, partage à bon escient, purge après audit si l'environnement l'exige.
- **Ne jamais** stocker le token dans un dashboard, un fichier de config commité, ou l'afficher dans une sortie.

## Auto-test hors ligne

Sans instance disponible (démo, CI, développement du skill) :

```bash
python3 scripts/forge_dashboards.py --selftest
```

Génère une capability map simulée (tous dialectes), rend les 6 blueprints, valide les invariants (IDs de panels uniques, gridPos dans la grille 24 colonnes, targets non vides, expressions référencées résolues) et écrit les JSON dans `./selftest_output/`. Utile aussi pour montrer à l'utilisateur à quoi ressembleront les dashboards avant de toucher à son instance.
