# grafana-llmops-forge en français

**Une seule condition : un Grafana joignable.** Le reste est **découvert, généré, déployé et vérifié visuellement** : ce que vos équipes consomment réellement en IA, ce que ça coûte par origine du fournisseur, ce que font vos agents, et les preuves d'observabilité qu'un auditeur réclamera.

➡ Le README complet est [en anglais ici](../README.md). Cette page en résume l'essentiel en français.

## Les trois questions auxquelles il répond

**« Combien l'IA nous coûte, et chez qui ? »** Dépense par jour, coût par requête, ventilation par origine du fournisseur, la donnée que demandent les directions achats pour les clauses contractuelles et la dépendance extra-européenne. Les coûts sont composés depuis un registre de 33 modèles à provenance vérifiée, ou calculés par des *recording rules* Prometheus quand vous les installez : les expressions sont plus courtes et les tarifs modifiables sans régénérer le tableau de bord ; le travail du moteur dépend toujours des séries et de la fenêtre. Les prix absents ou incomplets produisent un **sous-total explicitement nommé**, avec comptes de couverture et omission du budget. Au-delà de 40 modèles tarifés, la composition refuse tout montant : sélectionner la datasource, charger ses règles puis relancer découverte et forge. Toutes les valeurs métriques/modèles/providers retournées par le backend sont conservées ; cela ne garantit pas l'exhaustivité du backend. Une ancienne carte sans métadonnées cohérentes garde une estimation limitée aux modèles listés, sans budget jusqu'à une nouvelle découverte. Les coûts natifs/enregistrés conservent leur couverture amont non vérifiée, indépendante du registre.

**« Sommes-nous prêts pour l'audit ? »** Le même socle de télémétrie se lit contre trois référentiels (`--framework eu-ai-act,iso-42001,nist-rmf`). Le même volume de logs atteste l'Art. 12 de l'AI Act, le contrôle A.6.2.8 d'ISO/IEC 42001 et MANAGE 4.1 du NIST AI RMF ; le même inventaire de modèles répond à l'Art. 26, à A.10 et à GOVERN 6.1. Les panneaux mesurés sont identiques : seule la lecture change. Le tableau de bord dit aussi, noir sur blanc, **ce qu'il ne prouve pas** : ni système de management, ni analyse de risque, ni efficacité de la supervision humaine. *Support de preuve, pas un avis juridique.*

**« Est-ce que ça tient en production ? »** SLO de passerelle (latence p99, TTFT, taux d'erreur), inference self-hosted (vLLM, saturation KV-cache, GPU), et des alertes en **burn-rate à deux fenêtres** selon la méthode SRE plutôt qu'un seuil unique qui alerte trop tard sur les pannes lentes et trop souvent sur les pics inoffensifs.

## Origine fournisseur et lieux déclarés

Le champ `region` du registre et le label Prometheus correspondant restent compatibles : ils décrivent l'origine du fournisseur, **pas le lieu de traitement ou de stockage**. Le panneau de déploiement est indépendant de l'inventaire modèles. Sans déclaration, les lieux sont **inconnus**. Avec `--deployment-inventory ../instance/deployment_inventory.json`, un modèle d'origine américaine peut afficher un traitement déclaré en France ; les deux informations restent distinctes.

Le JSON local version 1 est limité à **1 Mio et 500 déploiements**, avec un identifiant unique par déploiement. Une correspondance exacte du modèle indique seulement sa présence dans la capability map. Endpoints, lieux, références de pièces et dates restent déclaratifs, sans contrôle indépendant. Aucune référence n'est consultée ou transformée en lien. La validation précède tout accès au fallback de prix/cache ou à Grafana, même en dry-run. Un inventaire multi-datasource est validé avant le filtrage ; seul le périmètre choisi est affiché. Conserver l'inventaire réel hors du dossier packagé, sans prompts ni secrets. Voir le [contrat et les restrictions de chemins locaux](deployment_inventory.md) et l'[exemple synthétique](deployment_inventory.example.json).

## S'intègre à votre plateforme existante

Les règles générées sortent en deux formats équivalents : le fichier portable (Prometheus, Thanos, Mimir/Cortex, VictoriaMetrics, AWS Managed Prometheus, Grafana Cloud) et un manifeste **`PrometheusRule`** pour Kubernetes sous Prometheus Operator, où vit la majorité des déploiements d'entreprise. La fenêtre `rate()` et l'intervalle d'évaluation s'ajustent à votre intervalle de scrape.

Les tableaux de bord sont générés **en anglais par défaut**, la langue de travail des équipes plateforme, et en français avec `--locale fr`.

## Côté sécurité et réversibilité

Python standard uniquement, **zéro dépendance**. Le jeton n'est jamais journalisé, le contenu des prompts jamais capturé par défaut. Déploiement idempotent et réversible : un dossier, des UID déterministes, relancer met à jour sans dupliquer. Le paquet `.skill` n'est jamais committé : la CI le construit de façon reproductible depuis les sources, vérifie fichier par fichier qu'il leur correspond, et le publie avec son empreinte.

Le projet est scanné par [NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector), qui ne relève **aucun constat** sur le livrable ; `SECURITY.md` explique ce qu'un scan du dépôt entier fait remonter et pourquoi chacun de ces points reste.

## Démarrage

```bash
make demo        # Grafana + Prometheus + charge LLM synthétique, en une minute

export GRAFANA_URL=https://grafana.interne.fr GRAFANA_TOKEN=glsa_...
python3 scripts/discover.py --out capability_map.json
python3 scripts/forge_dashboards.py --capability capability_map.json \
        --blueprints auto --deploy --with-alerts --locale fr
```

Utilisable aussi comme **Agent Skill** (Claude Code, Claude.ai, Cowork) : *« Audite mon Grafana, déploie ce qui est pertinent, puis prouve-le visuellement. »*
