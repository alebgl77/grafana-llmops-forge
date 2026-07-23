# Compatibilité API Grafana — OSS / Cloud / Enterprise (état juillet 2026)

Pourquoi la forge émet du **schéma classique v41 via l'API legacy** : c'est la
seule combinaison qui fonctionne identiquement de Grafana 9 à 13+, sur les
trois éditions, sans feature flag. Les nouveautés (schema v2, API resource) ne
sont utilisées qu'en fallback ou sur demande.

## 1. Trois générations d'API dashboards coexistent

| API | Endpoint | Dispo | Usage forge |
|---|---|---|---|
| Legacy | `POST /api/dashboards/db` (payload `{dashboard, folderUid, overwrite}`) | v9 → 13+, toutes éditions | **défaut** |
| Resource v1 | `/apis/dashboard.grafana.app/v1/namespaces/{ns}/dashboards[/{name}]` — le `spec` contient le modèle classique (`schemaVersion` 41/42) | v12+ (format d'échange par défaut entre 12.2 et 13.0) | fallback si legacy absent |
| Resource v2beta1/v2 | même groupe, `spec` = **schéma v2** (elements/layout séparés, base des dynamic dashboards, GA avril 2026) | v12 expérimental → GA récent | non émis par défaut (voir §4) |

Namespaces : `default` en self-hosted ; `stacks-<stack_id>` sur Grafana Cloud
(le client le lit dans `/api/frontend/settings`, fallback `default`).
Identité K8s-style : `metadata.name` = l'UID Grafana ; folder via l'annotation
`grafana.app/folder`.

## 2. Auth & rôles

- Service account token (`Authorization: Bearer glsa_…`) — recommandé partout.
  Les « API keys » historiques sont dépréciées/migrées en service accounts.
- Rôles : **Editor** suffit pour folders + dashboards. Le provisioning
  d'alertes (`/api/v1/provisioning/alert-rules`) exige des droits alerting —
  Admin sur OSS ; RBAC fin sur Enterprise/Cloud (`alert.provisioning:write`).
  En cas de 403, la forge exporte les règles en JSON (import manuel).
- Basic auth (`GRAFANA_USER`/`GRAFANA_PASSWORD`) : fallback labs/anciens setups.

## 3. Différences d'édition qui comptent

| Sujet | OSS | Enterprise | Cloud |
|---|---|---|---|
| Détection | défaut | `/api/licensing/check` ou `buildInfo.edition` | URL `*.grafana.net` |
| Datasource proxy `/api/datasources/proxy/uid/{uid}/…` | oui | oui | oui (base du discovery) |
| Provisioning alertes | oui (Admin) | oui (RBAC) | oui — attention aux limites de règles par stack |
| Reporting PDF (dashboard governance → comité) | non | oui | oui |
| RBAC fin, SCIM | non | oui | oui |
| Git Sync / as-code | expérimental | expérimental | preview |

## 4. Schéma v2 & dynamic dashboards — quand basculer

Depuis avril 2026, l'UI migre les dashboards ouverts vers le schéma v2
(tabs, layouts conditionnels). Conséquences pratiques :

- Un dashboard forge (classique v41) **reste valide** : Grafana le migre à la
  volée côté serveur/UI. Le POST legacy continue de fonctionner.
- Ne pas mélanger : si un humain ré-enregistre un dashboard forge dans l'UI
  (migration v2), le prochain upsert forge le ré-écrase en classique — c'est
  voulu (source de vérité = code), à annoncer à l'utilisateur.
- Générer nativement en v2 (tabs par domaine, conditionnels) : pertinent
  uniquement si l'instance est ≥ 13 partout et que l'équipe édite en as-code ;
  cible alors `/apis/dashboard.grafana.app/v2beta1` (ou v2 si GA sur
  l'instance) avec `spec` au format elements/layout. Hors périmètre du
  générateur actuel — extension possible sur demande.

## 5. Pièges opérationnels

- **UID ≤ 40 caractères**, alphanum + tirets — `det_uid()` le garantit.
- `overwrite: true` obligatoire pour l'idempotence legacy ; en resource API,
  PUT sur `/{name}` = update, POST = create (409 si existe).
- Grafana Cloud : rate limits API — la forge fait 1 appel/dashboard, négligeable.
- Le proxy datasource exige que le token ait accès en *query* à la datasource
  (permissions datasource sur Enterprise/Cloud).
- `/api/health` ne demande pas d'auth sur la plupart des setups — premier test
  de connectivité avant de diagnostiquer un problème de token.
