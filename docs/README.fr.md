# grafana-llmops-forge — pour les DSI francophones

**Une seule condition : un Grafana joignable.** Le reste — ce que vos équipes consomment réellement en IA, ce que ça coûte par fournisseur (🇪🇺/🇺🇸/🌏), ce que font vos agents, et les preuves d'observabilité que l'AI Act attend — est **découvert, généré, déployé et vérifié visuellement**.

➡ Le README complet (installation, architecture, sécurité) est [en anglais ici](../README.md). Cette page résume l'essentiel pour une DSI.

## Les trois questions auxquelles ça répond

1. **« Combien l'IA nous coûte, et chez qui ? »** — Dashboard FinOps : dépense/jour, coût par requête, ventilation par souveraineté du fournisseur (pilotage clauses contractuelles et dépendance US/Asie), coûts composés depuis un registre de 30+ modèles à prix vérifiés (rafraîchissable). Les modèles inconnus sont **exclus du calcul et listés**, jamais facturés au mauvais tarif.
2. **« Sommes-nous prêts pour l'AI Act ? »** — Dashboard gouvernance : calendrier réglementaire à jour (post-Digital Omnibus : sanctions actives 2 août 2026, Annexe III reportée déc. 2027), preuves de journalisation (Art. 12, rétention ≥ 6 mois Art. 26§6), inventaire automatique des modèles réellement utilisés (région, licence, périmètre GPAI), veille incidents (Art. 73). *Support d'audit — pas un avis juridique.*
3. **« Est-ce que ça tient en production ? »** — SLO gateway (latence p99, TTFT, erreurs), inference self-hosted (vLLM, saturation KV-cache, GPU), 5 alertes provisionnées dont dérive budgétaire quotidienne.

## Ce qui le distingue

- **Discovery-first** : aucun nom de métrique supposé — l'outil sonde vos datasources et ne génère que des panneaux qui afficheront des données. S'il manque des signaux : rapport d'écart avec les configs exactes (LiteLLM en ~30 min pour le spend natif).
- **Vérifié par l'œil** : après déploiement, capture du rendu réel (renderer natif ou navigateur) puis revue par vision IA — plausibilité des montants, panneaux vides, incohérences — avec boucle de correction bornée. On ne vous annonce jamais un succès non prouvé.
- **Auditable en une lecture** : Python standard uniquement, zéro dépendance, token jamais loggé, contenu des prompts jamais capturé par défaut, déploiement idempotent et réversible (un dossier, des UID déterministes).

## Démarrage (3 commandes)

```bash
export GRAFANA_URL=https://grafana.interne.fr GRAFANA_TOKEN=glsa_...
python3 scripts/discover.py --out capability_map.json
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints auto --deploy --with-alerts
```

Utilisable aussi comme **Agent Skill** (Claude Code, Claude.ai, Cowork — standard ouvert agentskills.io) : *« Audite mon Grafana et déploie ce qui est pertinent, puis prouve-le visuellement. »*
