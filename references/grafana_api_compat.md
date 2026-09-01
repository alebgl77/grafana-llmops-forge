# Compatibilité API Grafana : OSS / Cloud / Enterprise (état juillet 2026)

Pourquoi la forge émet du **schéma classique v41 via l'API legacy** : c'est la
seule combinaison qui fonctionne identiquement de Grafana 9 à 13+, sur les
trois éditions, sans feature flag. Les nouveautés (schema v2, API resource) ne
sont utilisées qu'en fallback ou sur demande.

## 1. Trois générations d'API dashboards coexistent

| API | Endpoint | Dispo | Usage forge |
|---|---|---|---|
| Legacy | `POST /api/dashboards/db` (payload `{dashboard, folderUid, overwrite}`) | v9 → 13+, toutes éditions | **défaut** |
| Resource v1 | `/apis/dashboard.grafana.app/v1/namespaces/{ns}/dashboards[/{name}]` ; le `spec` contient le modèle classique (`schemaVersion` 41/42) | v12+ (format d'échange par défaut entre 12.2 et 13.0) | fallback si legacy absent |
| Resource v2beta1/v2 | même groupe, `spec` = **schéma v2** (elements/layout séparés, base des dynamic dashboards, GA avril 2026) | v12 expérimental → GA récent | non émis par défaut (voir §4) |

Namespaces : `default` en self-hosted ; `stacks-<stack_id>` sur Grafana Cloud
(le client le lit dans `/api/frontend/settings`, fallback `default`).
Identité K8s-style : `metadata.name` = l'UID Grafana ; folder via l'annotation
`grafana.app/folder`.

## 2. Auth & rôles

- Service account token (`Authorization: Bearer glsa_…`) : recommandé partout.
  Les « API keys » historiques sont dépréciées/migrées en service accounts.
- Rôles : **Editor** suffit pour folders + dashboards. Le provisioning
  d'alertes (`/api/v1/provisioning/alert-rules`) exige des droits alerting ;
  Admin sur OSS ; RBAC fin sur Enterprise/Cloud (`alert.provisioning:write`).
  En cas de 403, la forge exporte les règles en JSON (import manuel).
- Basic auth (`GRAFANA_USER`/`GRAFANA_PASSWORD`) : fallback labs/anciens setups.

## 3. Différences d'édition qui comptent

| Sujet | OSS | Enterprise | Cloud |
|---|---|---|---|
| Détection | défaut | `/api/licensing/check` ou `buildInfo.edition` | URL `*.grafana.net` |
| Datasource proxy `/api/datasources/proxy/uid/{uid}/…` | oui | oui | oui (base du discovery) |
| Provisioning alertes | oui (Admin) | oui (RBAC) | oui, attention aux limites de règles par stack |
| Reporting PDF (dashboard governance → comité) | non | oui | oui |
| RBAC fin, SCIM | non | oui | oui |
| Git Sync / as-code | expérimental | expérimental | preview |

## 4. Schéma v2 & dynamic dashboards : quand basculer

Depuis avril 2026, l'UI migre les dashboards ouverts vers le schéma v2
(tabs, layouts conditionnels). Conséquences pratiques :

- Un dashboard forge (classique v41) **reste valide** : Grafana le migre à la
  volée côté serveur/UI. Le POST legacy continue de fonctionner.
- Ne pas mélanger : si un humain ré-enregistre un dashboard forge dans l'UI
  (migration v2), le prochain upsert forge le ré-écrase en classique ; c'est
  voulu (source de vérité = code), à annoncer à l'utilisateur.
- Générer nativement en v2 (tabs par domaine, conditionnels) : pertinent
  uniquement si l'instance est ≥ 13 partout et que l'équipe édite en as-code ;
  cible alors `/apis/dashboard.grafana.app/v2beta1` (ou v2 si GA sur
  l'instance) avec `spec` au format elements/layout. Hors périmètre du
  générateur actuel ; extension possible sur demande.

## 5. Pièges opérationnels

- **UID ≤ 40 caractères**, alphanum + tirets ; `det_uid()` le garantit.
- Sans `--uid-scope`, les UIDs historiques restent inchangés. Pour plusieurs
  dossiers/tenants, fournir un scope stable : dashboards **et** alertes auront
  des UIDs distincts. La forge refuse un UID existant dans un autre dossier.
- L'organisation vient de `/api/org` ou de `--org-id`; il n'existe aucun
  fallback silencieux vers l'org 1. Un override ajoute `X-Grafana-Org-Id` à
  toutes les requêtes, puis `/api/org` doit confirmer la même valeur. Un token
  qui ignore ce scope, une réponse ambiguë ou un refus d'accès interrompt le run.
- Avant l'update d'une alerte, la forge vérifie `uid`, `folderUID`, `orgID`,
  `ruleGroup`, le label d'origine et `llmops_rule_identity`, un SHA-256 du nom
  logique complet avant troncature de l'UID. Toute collision renvoie 409 avant
  le PUT et recommande `--uid-scope`. Une ancienne règle forge sans ce nouveau
  label est refusée de la même façon et doit être migrée explicitement.
- Une erreur datasource 401/403/429/5xx, proxy ou JSON invalide échoue par
  défaut. `--tolerate-datasource-errors` consigne l'erreur et continue seulement
  si une autre datasource est saine; une sélection explicite reste fail-closed.
- `overwrite: true` obligatoire pour l'idempotence legacy ; en resource API,
  PUT sur `/{name}` = update, POST = create (409 si existe).
- Grafana Cloud : rate limits API ; la forge fait 1 appel/dashboard, négligeable.
- Le proxy datasource exige que le token ait accès en *query* à la datasource
  (permissions datasource sur Enterprise/Cloud).
- `/api/health` ne demande pas d'auth sur la plupart des setups ; premier test
  de connectivité avant de diagnostiquer un problème de token.

`deploy_manifest.json` v2 porte `deployment_status`, `org_id`, `folder_uid`,
`uid_scope`, les compteurs requested/succeeded/failed/skipped par type et des
erreurs structurées. Un échec demandé produit un code non nul; `--best-effort`
autorise uniquement le code 0, sans transformer `partial|failed` en succès.

## 6. Où déposer les recording rules générées

La forge écrit deux fichiers équivalents ; le contenu des règles est identique,
seul l'emballage change selon la façon dont votre backend charge des règles.

| Environnement | Fichier | Comment le charger |
|---|---|---|
| Prometheus autonome | `prometheus_rules_llmops.yml` | `rule_files:` dans `prometheus.yml`, puis reload |
| Kubernetes + Prometheus Operator (kube-prometheus-stack) | `prometheusrule_llmops.yaml` | `kubectl apply -f` ; ajuster les labels au `ruleSelector` de votre Prometheus |
| Grafana Mimir / Cortex / Grafana Cloud | `prometheus_rules_llmops.yml` | `mimirtool rules load` (par tenant) |
| Thanos Ruler | `prometheus_rules_llmops.yml` | `--rule-file=` |
| VictoriaMetrics | `prometheus_rules_llmops.yml` | `vmalert -rule=` |
| AWS Managed Prometheus | `prometheus_rules_llmops.yml` | `aws amp create-rule-groups-namespace --data file://…` |
| Google Managed Prometheus | `prometheusrule_llmops.yaml` | la ressource `Rules` du rule-evaluator suit le même schéma |

Deux paramètres à accorder à votre plateforme avant de charger :

- `--rules-window` : la fenêtre `rate()`, à garder au-dessus de quatre fois
  l'intervalle de scrape. À 60 s de scrape, `5m` est le plancher pratique.
- `--rules-interval` : l'intervalle d'évaluation du groupe. Les offres managées
  imposent des minimums ; AMP et Mimir refusent le sous-minute par défaut.

Le `timeInterval` de votre datasource Grafana doit par ailleurs valoir votre
intervalle de scrape : `$__rate_interval` en dérive, et tous les panneaux
générés l'utilisent. Laissé vide, Grafana suppose 15 s et fausse silencieusement
chaque `rate()` sur une plateforme qui scrape plus lentement.
