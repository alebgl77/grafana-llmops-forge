---
name: grafana-llmops-forge
description: "Découvrir la télémétrie IA d'un Grafana, générer et déployer les dashboards compatibles, exporter les règles, puis capturer le rendu pour une revue distincte. Couvre coûts, SLO, agents, adoption, inference, qualité et preuves de gouvernance EU AI Act, ISO/IEC 42001 et NIST AI RMF. Sortie anglaise ou française."
---

# Grafana LLMOps Forge : guide français

Ce guide résume le [protocole canonique](../SKILL.md). Il accompagne le dépôt ;
le paquet distribué utilise le `SKILL.md` racine. Lire ce protocole avant une
intervention, notamment ses limites d'accès, de déploiement et de preuve.

## Principes

- Partir des métriques et des labels découverts. Ne pas inventer de signal.
  La découverte ne garantit pas des résultats sur toutes les plages temporelles.
- Séparer les résultats : génération, déploiement, capture technique et revue
  visuelle. Une capture réussie n'est pas une validation de la justesse des chiffres.
- Ne générer que les blueprints compatibles. La gouvernance peut documenter les
  lacunes sans signal LLM. Ne pas déployer des squelettes décoratifs.
- Préserver une seule source financière : en mode automatique, priorité
  `recorded`, puis `native`, puis `inline`. Une ambiguïté entre datasources de
  même priorité exige `--datasource UID`. Ne jamais additionner leurs coûts.
- L'origine du fournisseur dans le registre n'indique ni le lieu de traitement,
  ni le stockage, ni une souveraineté garantie.
- Générer en anglais par défaut ; passer `--locale fr` pour les libellés français.
  Les trois cadres de gouvernance sont inclus par défaut ; filtrer avec
  `--framework eu-ai-act,iso-42001,nist-rmf`.
- Ne jamais exposer les identifiants. Les fournir par variables d'environnement.
  Les scripts restent en Python standard, sans LLM ; Playwright est optionnel.

## Parcours

### 1. Découvrir

Définir `GRAFANA_URL` et les identifiants autorisés, puis exécuter :

```bash
python3 scripts/discover.py --out capability_map.json
```

Lire version, APIs, datasources, métriques, labels, modèles observés et lacunes.
Pour cibler une organisation, utiliser `--org-id` ; pour lever une ambiguïté
Prometheus, `--datasource UID`. Lire les
[compatibilités](../references/grafana_api_compat.md) en cas de doute.

### 2. Vérifier provenance et couverture

Lire le registre et sa date de vérification. Le runtime ne rafraîchit pas
automatiquement les prix officiels sur le Web. Vérifier les sources officielles
si une mise à jour est nécessaire, puis consigner provenance et date.

Les dépenses natives et les coûts enregistrés gardent leur provenance amont.
L'estimation inline utilise les modèles et alias exacts. Prix manquant ou ambigu :
signaler la lacune ; ne pas fabriquer un montant nul. Une couverture partielle
peut supprimer les montants ou rendre l'alerte de budget inéligible.

Le recours à Artificial Analysis est désactivé par défaut et exige
`--pricing-fallback artificial-analysis` avec `ARTIFICIAL_ANALYSIS_API_KEY`.
Les résultats restent des estimations tierces identifiées. Lire la
[provenance financière](../references/pricing_provenance.md).

Un inventaire local peut déclarer les lieux de déploiement via
`--deployment-inventory FILE`. Sans inventaire, les lieux restent inconnus.
Ces déclarations ne sont pas des vérifications indépendantes :
[format et validation](deployment_inventory.md).

### 3. Choisir les sept blueprints

| Clé | Finalité |
|---|---|
| `finops` | Dépenses, rythme de coût, provenance et couverture |
| `gateway` | Latence, erreurs, TTFT et disponibilité |
| `agents` | Opérations, outils et traces des agents |
| `adoption` | Usage par équipe, service et modèle |
| `inference` | Serveurs d'inférence, files, tokens et GPU |
| `quality` | Évaluations et garde-fous ; distinguer histogrammes et scores simples |
| `governance` | Preuves observées, inventaire et déclarations de déploiement |

Lire les [spécifications des blueprints](../references/dashboard_blueprints.md).
En mode `auto`, une télémétrie incomplète produit moins de sept dashboards.

### 4. Générer et déployer dans le périmètre autorisé

```bash
python3 scripts/forge_dashboards.py --capability capability_map.json \
  --blueprints auto --locale fr --dry-run --out-dir generated_dashboards
# Une fois le déploiement autorisé :
python3 scripts/forge_dashboards.py --capability capability_map.json \
  --blueprints auto --locale fr --deploy --with-alerts --out-dir generated_dashboards
```

Les ressources utilisent le dossier dédié et des UIDs déterministes.
Pour plusieurs dossiers gérés indépendamment, fixer un `--uid-scope` stable.
Expliquer le retour arrière avant déploiement : le client ne supprime rien ;
l'exploitant peut supprimer le dossier créé et retirer séparément les règles
Prometheus. Ne pas toucher aux ressources préexistantes hors de ce périmètre.

Lire le manifeste de déploiement v2 et les statuts par ressource.
`--best-effort` peut assouplir le code retour ; il ne transforme pas un résultat
partiel en réussite. Les règles exportées en YAML et PrometheusRule doivent être
installées côté Prometheus, rechargées puis évaluées. Rediscover et re-forge
permettent ensuite d'utiliser les séries enregistrées.

### 5. Capturer, puis examiner

```bash
python3 scripts/visual_audit.py --dashboards generated_dashboards --out visual_audit
```

Le moteur renderer produit les PNG ; Playwright fournit une solution de repli
avec précontrôles DOM. Lire `audit_manifest.json`, ses chemins `files[]`, captures
manquantes, erreurs et `org_id`. Les dossiers sont isolés par instance,
organisation et UID. Un statut `success` concerne uniquement la capture et les
précontrôles. `--allow-empty` peut assouplir le code retour mais laisse le
manifeste en échec.

Ouvrir les PNG et appliquer la
[checklist de revue](../references/visual_verification.md). Consigner le
périmètre, le reviewer et le verdict. Sans inspection effective, indiquer
« revue visuelle non effectuée ». Corriger à la source, régénérer et recapturer
les dashboards concernés ; ne pas considérer la CI comme un verdict de vision.

### 6. Restituer

Rapporter séparément ce qui a été généré, déployé, capturé et examiné, les
lacunes de télémétrie, la provenance des coûts et les limites restantes.
Lier les [configurations d'instrumentation](../references/instrumentation_guide.md)
utiles. Les correspondances
[EU AI Act / ISO / NIST](../references/ai_governance_frameworks.md) sont un appui
à l'audit, sans certification ni avis juridique. Revérifier les références
réglementaires applicables avant une utilisation décisionnelle.

## Vérification hors ligne

```bash
python3 scripts/forge_dashboards.py --selftest --with-alerts
python3 tests/audit_harness.py
python3 tests/visual_capture_invariants.py
python3 tests/project_coherence.py
python3 tools/package.py
python3 tools/package.py --verify
```

Le selftest utilise une capability map simulée. Les tests Prometheus/Grafana
réels et la revue visuelle sur l'instance cible restent distincts.
