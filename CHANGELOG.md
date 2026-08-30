# Changelog

## [1.2.2] — 2026-08-30
### Fixed — chemins d'export Prometheus (deux angles morts reproduits sur instance réelle)
- **Préfixe de namespace invisible.** Les regex Prometheus sont ancrées : la signature `gen_ai_.*` ne matchait pas `myapp_gen_ai_...`, produit par l'option `namespace` des exporters OTel Collector ou par un `metric_relabel_configs`. La forge annonçait « aucun signal LLM » sur une stack parfaitement instrumentée. Signatures désormais tolérantes au préfixe.
- **Noms UTF-8 non supportés.** Avec `translation_strategy: NoTranslation` (Prometheus ≥ 3.0), les noms OTel gardent leurs points (`gen_ai.client.token.usage`) et les labels aussi. Ces séries n'étaient ni découvertes, ni interrogeables : un nom pointé nu renvoie HTTP 400, il faut la syntaxe `{"nom", label="v"}`. Ajout des helpers `msel`/`qlbl`, routage de toutes les compositions métrique/label, résolveur de signaux insensible au séparateur.

### Fixed — recording rules muettes
- Les prix et le coût étaient déclarés dans **deux groupes de règles distincts**. Prometheus évalue les groupes en parallèle et décale leur démarrage : la règle de coût pouvait s'exécuter avant l'existence des prix et ne rien produire, avec `health=ok` — donc silencieusement. Un seul groupe désormais, où l'ordre séquentiel est garanti. Vérifié : 5 séries de coût matérialisées, bascule automatique en mode `recorded`.

### Verified
38/38 expressions exécutées sans erreur sur un Prometheus réel pour les trois variantes (classique, préfixée, UTF-8) ; 63/63 sur la stack de démo complète, sans régression. Tests permanents ajoutés au harnais.

## [1.2.1] — 2026-08-30
### Fixed
- **Échappement regex PromQL** (bug trouvé par le nouveau contrôle live, invisible hors ligne) : `re.escape` produisait `\-`, rejeté par RE2, et un `\.` simple était consommé par le littéral chaîne du matcher avant d'atteindre la regex. Le panel « Trafic par souveraineté » était cassé pour tout modèle contenant un tiret ou un point — c'est-à-dire presque tous.

### Added
- `tests/live_query_check.py` : sonde un vrai Prometheus, construit la capability map à partir de ce qu'il y trouve, lance la forge et **exécute chaque expression générée** (63 sur la stack de démo). Le harnais hors ligne valide la structure ; celui-ci valide la sémantique.

### Verified on real data
- 63/63 expressions renvoient des données ; recording rules auto-détectées (dialecte `recorded`) et coût basculé en O(1) : `(sum(llm:cost_usd_per_second) or vector(0)) * 86400` → 337,36 USD/jour, ventilé 🇪🇺 3,12 / 🇺🇸 329,63 / 🌏 4,61.

## [1.2.0] — 2026-08-30
### Fixed (bugs réels, tous couverts par des tests de non-régression)
- **L'alerte « signal perdu » était muette quand le signal se perdait vraiment** : `noDataState: OK` faisait taire la règle si la datasource devenait injoignable. Passée à `Alerting`.
- **Panel Loki de gouvernance typé `prometheus`** : type de datasource désormais explicite (cassait aussi l'export portable).
- **`orgID: 1` en dur** dans les règles d'alerte → org réelle lue via `/api/org` (multi-org Enterprise/Cloud).
- **`$__rate_interval` dans les règles d'alerte** → fenêtres explicites, l'intervalle d'une règle n'étant pas celui d'un panel.
- Multi-datasource silencieux : `discover.py` signale les instances portant plusieurs sources LLM, `--datasource` permet de trancher.

### Added
- **Recording rules de coût** : prix en séries + `llm:cost_usd_per_second` joint par vector matching. Panels FinOps en O(1), nombre de modèles illimité (plafond inline relevé 14 → 40), tarifs modifiables sans regénérer les dashboards. Détection automatique du mode (`--cost-mode auto|recorded|inline`).
- **Alerting burn-rate multi-fenêtres** (5m/1h critique, 30m/6h avertissement) sur le budget d'erreur, `--slo-target`.
- **7e blueprint « Qualité & Évaluations »** (scores RAGAS / juge LLM, garde-fous, volume d'évals) + alerte de chute de score.
- **Exemplars et liens métrique → trace Tempo** sur les panels de latence, avec détection du routage exemplar côté datasource.
- **`--export-portable`** : JSON avec `__inputs`/`${DS_*}`, format requis par grafana.com/dashboards.
- **Stack de démo** `make demo` : Grafana + Prometheus + émetteur de métriques LLM synthétiques (stdlib), utilisée aussi comme **test end-to-end réel en CI**.
- Avertissement si aucun contact point n'est configuré (alertes sans destinataire).
- Workflow mensuel de fraîcheur du registre de prix.

### Hardened
- **Cardinalité** : garde-fou dur (aucun group-by au-delà de 300 valeurs distinctes) et bornage `topk` sur tous les panels groupés (équipes, services, agents, outils, logs) — un graphe à 300 courbes est illisible *et* lent.
- `maxDataPoints: 500` sur toutes les séries temporelles : coût de requête borné sur les longues plages.
- Visuels du README explicitement étiquetés « illustration, pas capture » ; `make demo` fournit le rendu réel.

### Changed
- SKILL.md intégralement en anglais (le déclenchement suivait mal les requêtes anglophones) ; version française conservée dans `docs/SKILL.fr.md`.
- Harnais d'audit : 27 → 41 contrôles.

## [1.1.0] — 2026-07-23
### Added
- Visual verification layer: `visual_audit.py` (native renderer + Playwright fallback, DOM pre-scan), vision checklist & remediation protocol (`references/visual_verification.md`), `deploy_manifest.json`.
- Offline audit harness: 27 checks across 4 instance topologies (`tests/audit_harness.py`).
### Fixed
- **Billing-accuracy bug**: model matcher now scores by specificity — `gpt-5.4-mini` can no longer be priced as `gpt-5.4` (was ×5.5 overcost). Regression-tested.
### Hardened
- Per-dashboard capture isolation; tolerance for hand-made capability maps.

## [1.0.0] — 2026-07-12
- Initial release: discovery-first pipeline, 6 blueprints, 4 dialects, 30-model registry (verified 2026-07-12), 5 SLO alerts, EU AI Act mapping (post-Digital-Omnibus timeline).
