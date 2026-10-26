# grafana-llmops-forge en français

**À partir d'un Grafana joignable et des accès nécessaires**, la forge découvre la télémétrie, génère et déploie les dashboards IA/LLM, puis propose des captures pour une revue visuelle distincte : usages, coûts par origine du fournisseur, activité des agents et éléments d'observabilité utiles à un audit.

➡ Le README complet est [en anglais ici](../README.md). Cette page en résume l'essentiel en français.

## Les trois questions auxquelles il répond

**« Combien l'IA nous coûte, et chez qui ? »** Dépense par jour, coût par requête, ventilation par origine du fournisseur, la donnée que demandent les directions achats pour les clauses contractuelles et la dépendance extra-européenne. Les coûts sont composés depuis un registre de 33 modèles à provenance vérifiée, ou calculés par des *recording rules* Prometheus quand vous les installez : les expressions sont plus courtes et les tarifs modifiables sans régénérer le tableau de bord ; le travail du moteur dépend toujours des séries et de la fenêtre. Les prix absents ou incomplets produisent un **sous-total explicitement nommé**, avec comptes de couverture et omission du budget. Au-delà de 40 modèles tarifés, la composition refuse tout montant : sélectionner la datasource, charger ses règles puis relancer découverte et forge. Toutes les valeurs métriques/modèles/providers retournées par le backend sont conservées ; cela ne garantit pas l'exhaustivité du backend. Une ancienne carte sans métadonnées cohérentes garde une estimation limitée aux modèles listés, sans budget jusqu'à une nouvelle découverte. Les coûts natifs/enregistrés conservent leur couverture amont non vérifiée, indépendante du registre.

**« Sommes-nous prêts pour l'audit ? »** Le même socle de télémétrie se lit contre trois référentiels (`--framework eu-ai-act,iso-42001,nist-rmf`). Le même volume de logs atteste l'Art. 12 de l'AI Act, le contrôle A.6.2.8 d'ISO/IEC 42001 et MANAGE 4.1 du NIST AI RMF ; le même inventaire de modèles répond à l'Art. 26, à A.10 et à GOVERN 6.1. Les panneaux mesurés sont identiques : seule la lecture change. Le tableau de bord dit aussi, noir sur blanc, **ce qu'il ne prouve pas** : ni système de management, ni analyse de risque, ni efficacité de la supervision humaine. *Support de preuve, pas un avis juridique.*

**« Est-ce que ça tient en production ? »** SLO de passerelle (latence p99, TTFT, taux d'erreur), inference self-hosted (vLLM, saturation KV-cache, GPU), et des alertes en **burn-rate à deux fenêtres** selon la méthode SRE plutôt qu'un seuil unique qui alerte trop tard sur les pannes lentes et trop souvent sur les pics inoffensifs.

Le tarif exige un ID ou alias normalisé exact, avec suffixe de date valide seulement pour une identité de base exacte. Une simple sous-chaîne reste non tarifée. Un total inline exige au moins une composante tarifée calculable : l'absence complète de télémétrie reste inconnue, tandis qu'un usage nul observé reste zéro. Si une seule direction est disponible, le remplissage existant à zéro des directions manquantes reste appliqué ; il ne prouve pas l'exhaustivité de la dépense. Les jointures de coûts enregistrés retirent les dimensions source `region`/`vendor` avant de poser l'origine fournisseur du registre.

Les alertes de burn évaluent le résultat instantané des deux fenêtres : les anciens points ne prolongent pas une alerte après récupération. Un résultat absent ou sans trafic suit `noDataState: OK` ; l'alerte distincte de perte de télémétrie détecte le trafic manquant. Le contrôle live échoue sur erreur HTTP/transport, réponse mal formée, valeur non finie après une attente de chauffe bornée ou absence de requêtes vérifiées. La CI des Grafana pris en charge teste aussi la récupération avec une datasource contrôlée ; promtool valide séparément les calculs PromQL.

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

## Ce qui est vérifié, et par qui

| Couche | Exécution et portée |
|---|---|
| Tests hors ligne, requêtes Prometheus, invariants de valeurs et déploiement Grafana | Automatisés en CI ; le job E2E ne lance ni renderer ni modèle de vision. |
| Captures et précontrôles | `visual_audit.py` produit les PNG ; le mode Playwright préanalyse les marqueurs d'erreur du DOM. Les chemins d'échec de capture sont testés hors ligne en CI. |
| Revue sémantique du rendu | Optionnelle et distincte, réalisée par une personne ou un agent capable de lire les images ; elle ne tourne pas en CI. |

Après le déploiement, `python3 scripts/visual_audit.py --dashboards generated_dashboards`
prépare les captures. Un `audit_status: success` décrit la capture et les
précontrôles, sans verdict sur la cohérence des chiffres ou la lisibilité.
Pour annoncer une vérification visuelle, inspecter les PNG avec le
[protocole de revue](../references/visual_verification.md) et consigner le
verdict. Sinon, indiquer **revue visuelle non effectuée**. Les statuts du
déploiement, des captures et de la revue doivent rester distincts.

## Feuille de route

**Chaque changement IA, une décision que vous pouvez justifier.** L'orientation proposée vise des décisions opérationnelles reproductibles pour les entreprises européennes sur Grafana auto-hébergé, à partir de leurs outils de télémétrie et d'évaluation existants.

Ces horizons sont prévus avec des critères de passage, sans dates de livraison :

- **H0 · Des fondations fiables :** mesures interprétables, lacunes explicites et diffs de configuration en lecture seule.
- **H1 · Comparer un changement :** coût par tâche réussie à qualité et latence explicites, avec refus motivé lorsque les éléments sont insuffisants.
- **H2 · Livrer avec des preuves :** dossiers portables de promotion et contrôles consommés par la CI et les outils de provisioning du client.
- **H3 · Répéter la prochaine migration :** tests de migration exécutés ou scénarios de sensibilité clairement identifiés, après validation de l'utilité du parcours précédent.

Au 2026-10-27, **v2.0.5 est la version publiée de référence**. Elle distingue
les illustrations statiques, la capture live des tableaux de bord et la revue
sémantique optionnelle ; met à jour la CI vers setup-python 7.1.0 avec lancement
manuel ; et rafraîchit la démo vers Python 3.15 et Prometheus 3.15.1. Un invariant
empêche désormais toute dérive de version entre la datasource et le runtime
Prometheus. Dependabot reste limité au manifeste Docker Compose de `/demo` et
ignore l'image Grafana pilotée par la matrice. Les corrections de citation et de
préparation à la production des versions précédentes restent incluses. Les
parcours de comparaison et dossiers proposés restent des travaux futurs.

Consulter la [feuille de route française](ROADMAP.fr.md) ou la [version anglaise canonique](../ROADMAP.md) pour la démonstration future, le périmètre et les critères de passage.

## Auteur

Conçu et maintenu par **[Alexandre Beguel](https://github.com/alebgl77)**, architecte IA agentique et CAIO externalisé basé à Paris. Il travaille sur l'IA générative en production, le LLMOps, le FinOps des LLM et la gouvernance de l'IA fondée sur les preuves. [beguel.com](https://beguel.com/) · [LinkedIn](https://www.linkedin.com/in/beguel/) · [Profil en français, anglais et espagnol](https://alebgl77.github.io/fr/)
