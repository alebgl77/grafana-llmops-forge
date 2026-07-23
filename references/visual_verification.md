# Vérification visuelle — protocole vision

La forge valide le JSON et l'API valide l'ingestion ; **seule la vision valide
le rendu**. Ce protocole s'applique aux PNG produits par `visual_audit.py`.
C'est Claude qui regarde : ouvrir les images (outil de lecture de fichiers) et
appliquer les checklists ci-dessous. Ne jamais déclarer un déploiement réussi
sans verdict visuel quand la capture est possible.

## 1. Moments stratégiques (quand déclencher)

| Moment | Portée | Obligatoire |
|---|---|---|
| Juste après `forge --deploy` | full.png de chaque dashboard, puis panels douteux | **oui** |
| Avant remise du dashboard governance (pièce d'audit) | tous les panels du dashboard | **oui** |
| Après avoir comblé un gap d'instrumentation | dashboards impactés par le nouveau signal | oui |
| Après modification du registre de prix | finops (échelles $ plausibles) | oui |
| Vérification de paramétrage (datasource, règle d'alerte, variable) | page concernée — **Playwright uniquement** (le renderer ne rend que les dashboards) | à la demande |
| Instance de prod inconnue / premier contact | 1 dashboard témoin avant de générer les 6 | recommandé |

## 2. Séquence

```bash
python3 scripts/visual_audit.py --dashboards generated_dashboards --out visual_audit
# puis : ouvrir visual_audit/<dash>/full.png (vision), croiser avec audit_manifest.json
# (panel_index = correspondance fichier → titre ; dom_findings = pré-scan Playwright)
```

Ordre de lecture : `full.png` d'abord (structure, panels vides, erreurs
visibles), puis les `panel_XX_*.png` de tout panel douteux. Sur Playwright, les
`dom_findings` du manifeste priorisent l'inspection (« No data » ×3 → aller
voir ces trois panels en premier).

## 3. Checklist vision — par capture

**Déterministe (échec net) :**
- Panel « No data » / « N/A » alors que la capability map a détecté le signal.
- Coin rouge / message d'erreur de requête ; « Datasource not found » ;
  « Panel plugin not found ».
- Dropdown de variable `$model` vide ou bloqué sur « None ».
- Stat affichant `NaN`, `Inf`, ou un temps de type `14 s` là où on attend des ms.
- Panel tronqué, superposé, ou titre coupé rendant la lecture impossible.

**Sémantique (le vrai apport de la vision) :**
- **Plausibilité d'échelle** : disponibilité ∈ [0 ; 1] ; un coût/jour à
  0,000004 $ = prix par token appliqué deux fois ; un coût à 40 000 $/j sur une
  équipe de 10 = tokens comptés en double (input+output+total sommés).
- **Cohérence inter-panels** : tokens/s > 0 mais dépense = 0 → modèles non
  matchés au registre (vérifier le panel « hors registre ») ; req/s > 0 mais
  latence vide → histogramme absent, seul le count existe.
- **Formes suspectes** : série parfaitement plate ≠ 0 sur 24 h (métrique
  figée / scrape cassé) ; escalier géant unique (counter reset mal géré) ;
  p50 > p95 (jamais possible → bug de requête).
- **Lisibilité décisionnelle** : légendes = noms de modèles humains (pas des
  UUID) ; unités affichées ($ , s, req/s) ; stacked réellement empilé ;
  le dashboard répond à sa question en < 10 s de lecture.
- **Governance** : tableau d'inventaire complet et daté, calendrier lisible,
  alertlist rendue (même vide : « aucune alerte » est un état valide).

## 4. Signatures → causes → correctifs

| Symptôme visuel | Cause probable | Correctif |
|---|---|---|
| « No data » partout sur un dashboard | mauvaise datasource (uid), ou time range hors données | vérifier capability map ; recapturer avec `--time-from now-7d` |
| « No data » sur les seuls panels de coût | label `gen_ai_token_type` ≠ celui supposé, ou modèles non matchés | re-lancer discover (sonde token_type_label) ; ajouter aliases au registre ; re-forge |
| Latences vides, débit OK | exporter n'émet que `_count` (histogramme désactivé) | activer les histogrammes côté instrumentation (guide §2) |
| Stat coût ridicule/énorme | prix/M appliqué sans ÷1e6, double comptage, ou unité panel fausse | comparer à `spend litellm` si dispo ; corriger registre ; re-forge |
| Variable $model vide | `label_values()` sur mauvaise métrique/label | vérifier `model_label` de la capability map |
| Page de login dans le PNG (Playwright) | Bearer refusé par un proxy SSO | exporter `GRAFANA_COOKIE` (cookie de session) et relancer |
| PNG blanc/incomplet (Playwright) | requêtes non terminées | augmenter `--settle-ms 9000` |
| 404 sur /render | plugin renderer absent | §5 ci-dessous, ou `--engine playwright` |
| Quantiles en marches d'escalier grossières | buckets d'histogramme trop rares | noter la limite ; ajuster les buckets côté exporter si critique |

## 5. Moteur renderer natif (recommandé en self-hosted)

```bash
grafana-cli plugins install grafana-image-renderer && systemctl restart grafana-server
# ou service distant :
docker run -d -p 8081:8081 grafana/grafana-image-renderer:latest
# grafana.ini → [rendering] server_url=http://renderer:8081/render callback_url=http://grafana:3000/
```
Grafana Cloud : inclus (quotas de rendus). Le renderer EST un navigateur
headless côté serveur : c'est bien le rendu réel de l'interface.

## 6. Vérification de paramétrage (au-delà des dashboards)

Playwright uniquement — capturer ces URLs avec le même header d'auth :
`/connections/datasources` (datasources saines), `/alerting/list` (règles forge
présentes et évaluées), `/dashboards?tag=llmops-forge` (inventaire). Même
checklist : état attendu visible, aucun badge d'erreur.

## 7. Boucle de remédiation (protocole)

1. Verdict par dashboard : ✅ conforme / ⚠ dégradé (fonctionne, lisibilité ou
   signal partiel) / ❌ défaillant.
2. Pour chaque ⚠/❌ : diagnostiquer via §4, corriger **à la source** (registre,
   capability map re-sondée, code forge) — jamais dans l'UI Grafana.
3. Re-forge → re-déploiement → re-capture **des seuls dashboards corrigés**.
4. Maximum 2 itérations ; au-delà, livrer le verdict honnête avec captures à
   l'appui et le plan de correction restant.
5. Restitution : tableau verdicts + 1 phrase de preuve par dashboard
   (« finops : dépense 87 $/j cohérente avec 61 M tokens gpt-5.4 »).

Confidentialité : les PNG peuvent contenir noms d'équipes, coûts, modèles —
les stocker localement, ne les partager qu'à bon escient, les purger après
audit si l'environnement l'exige.
