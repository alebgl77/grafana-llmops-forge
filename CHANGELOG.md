# Changelog

## [2.0.0] - 2026-09-01
### Changed : chaîne de déploiement et de preuve v2
- **Rupture de compatibilité : manifests v2 et portée organisationnelle stricte.** Les artefacts de déploiement portent désormais leur contrat de version, l'organisation cible est vérifiée sans repli implicite, et un garde-fou bloque les collisions avant toute écriture.
- **Audit visuel fail-closed et Playwright durci.** Une preuve visuelle manquante ou invalide fait échouer l'audit ; l'exécution du navigateur applique les limites et contrôles de sécurité attendus.
- **Release reproductible avec SBOM.** La chaîne de publication produit et vérifie ses artefacts de supply chain, tandis que la CI couvre Grafana 9 à 13.
- **Registre de prix rafraîchi depuis les sources officielles.** Chaque entrée expose sa provenance et sa date de vérification ; les tarifs absents restent non chiffrés. Artificial Analysis n'est disponible qu'en fallback tiers opt-in, avec attribution et restrictions de redistribution explicites.

## [1.6.0] - 2026-08-30
### Fixed : exploitabilité en production
- **Un 403 de permissions sortait une trace Python.** Un exploitant ne pouvait pas savoir qu'il s'agissait d'un rôle de jeton insuffisant, ni dans quel état il avait laissé l'instance. Message actionnable nommant le rôle requis, codes de sortie distincts (3 = rien écrit, 4 = déploiement partiel), et l'emplacement des JSON générés pour un import manuel.
- **Un échec sur un dashboard annulait les suivants.** Le déploiement continue désormais, décrit précisément l'état atteint, et rappelle que relancer est sûr : les UID déterministes en font une mise à jour.
- **Suppression de la méthode `delete()` du client**, jamais appelée. Un relecteur sécurité y voyait une capacité de suppression ; la garantie de rayon de souffle devient structurelle plutôt que conventionnelle.

### Added
- **Procédure de retour arrière documentée.** La question qu'un comité de changement pose en premier n'avait pas de réponse. Tout vit dans un dossier, l'outil n'a aucun chemin de suppression, retirer ce dossier retire tout le déploiement. Avec le tableau de ce qui est écrit et où.
- **Divulgation explicite** : rien ne quitte le réseau hors rafraîchissement optionnel des prix ; et ce qu'un agent voit : la capability map contient des métadonnées organisationnelles, ce qui se contourne en exécutant les scripts en CLI pure.
- `tests/fake_grafana.py` : instance simulée à pannes ciblées. Harnais sections [25] et [26] (rayon de souffle et comportement en panne), soit 161 contrôles au total.

## [1.5.2] - 2026-08-30
### Fixed : la documentation avait pris du retard sur le produit
- **La description du SKILL.md ne mentionnait ni ISO 42001, ni NIST, ni les langues.** C'est le texte qui déclenche le skill : une demande de preuves ISO 42001 dans Grafana ne l'aurait pas activé. Défaut fonctionnel, pas cosmétique.
- **Le frontmatter est devenu invalide en le corrigeant** (un `: ` dans un scalaire non quoté) et le harnais ne l'a pas vu : il vérifiait la longueur par regex, jamais que le YAML parse. Un skill au frontmatter cassé ne charge pas du tout. Contrôle ajouté.
- `docs/README.fr.md` était figé avant l'internationalisation, la gouvernance multi-référentiels et le format Kubernetes. Réécrit.
- Le brouillon Show HN ignorait ISO/NIST et l'anglais par défaut, deux arguments de vente majeurs.
- Le playbook de lancement recommandait les listes awesome **avant** la traction. L'expérience dit l'inverse : plusieurs listes filtrent sur un seuil d'étoiles. Séquence corrigée, avec l'état réel de la première vague.

### Added
- Harnais section [24] : la documentation utilisateur, le brouillon de lancement et les liens internes sont comparés au produit à chaque exécution.

## [1.5.1] - 2026-08-30
### Fixed : les visuels avaient dérivé du produit
Confrontés programmatiquement au code plutôt qu'à l'œil, les quatre schémas mentaient sur quatre points :
- **Le mockup phare du README était en français** alors que le produit sort en anglais par défaut depuis la 1.3.0. Quiconque comparait l'image et l'outil trouvait deux choses différentes. Réaligné mot pour mot sur les titres réellement générés.
- Le banner annonçait « 6 dashboards » et « 4 dialects » (il y en a 7 et 10) et « EU AI Act ready », alors que la gouvernance couvre trois référentiels.
- Les intitulés du crosswalk visuel divergeaient de `CROSSWALK_ROWS`.
- Le schéma d'architecture omettait `grafana_client.py`.
- Emojis drapeaux retirés : ils tombent en tofu selon la police disponible, ce que la revue par vision a montré.

### Added
- Harnais section [23] : le nombre de dashboards et de dialectes annoncés, les titres du mockup, les lignes du crosswalk et les scripts cités sont désormais **dérivés du code et comparés aux visuels** à chaque exécution. Un visuel ne peut plus vieillir en silence.

## [1.5.0] - 2026-08-30
### Added : la gouvernance parle enfin à autre chose qu'à l'Europe
- **ISO/IEC 42001:2023 et NIST AI RMF 1.0** rejoignent l'EU AI Act dans le tableau de bord de gouvernance. Le même volume de logs atteste l'Art. 12, le contrôle A.6.2.8 et MANAGE 4.1 : c'est une lecture qui change, pas une instrumentation. Une organisation qui vise la certification ISO et une autre qui raisonne en RMF ne se reconnaissaient ni l'une ni l'autre dans un tableau de bord mono-juridiction.
- `--framework eu-ai-act,iso-42001,nist-rmf` (défaut) sélectionne les lectures rendues. La table de correspondance est générée depuis des données : elle n'affiche que les colonnes demandées, et ajouter un référentiel est une clé de plus, pas un panneau de plus.
- `references/ai_governance_frameworks.md` : le crosswalk complet, ce que chaque cadre est réellement, et surtout **ce que le tableau de bord ne prouve pas** : un système de management (clauses ISO 4-10), une analyse de risque, l'efficacité de la supervision humaine, la rétention effective. Un tableau de bord de gouvernance survendu est pire que pas de tableau de bord.
- Les numéros de contrôle Annexe A varient entre sources secondaires ; le document le dit et renvoie à la norme, dont le texte est payant et invérifiable d'ici.

### Verified
Triple contrôle. Hors ligne : cinq combinaisons de `--framework`, UID stable (mise à jour et non duplication), référentiel inconnu géré, sept options de génération. Sur Prometheus réel : 63/63 expressions par combinaison, invariants de valeur respectés, les référentiels n'ayant touché à aucune requête. Indépendamment : yamllint, zizmor, promtool sur les deux formats de règles, 123 contrôles du harnais, paquet conforme aux sources, scan de sécurité à zéro constat.

## [1.4.0] - 2026-08-30
### Added : les règles générées s'installent dans n'importe quelle plateforme
- **Manifeste `PrometheusRule` émis à côté du fichier plat.** La majorité des déploiements d'entreprise tournent sous Kubernetes avec le Prometheus Operator, qui n'accepte pas un fichier de règles brut. Mêmes règles, deux emballages, validés identiques par promtool à chaque build.
- **`--rules-window` et `--rules-interval`.** La fenêtre `rate()` était figée à 5 minutes : correct à 10 s de scrape, faux à 60 s. Et les backends managés (AMP, Mimir) refusent les groupes sous la minute.
- En-tête du fichier de règles documentant la recette de chargement par backend : Prometheus, Thanos, Mimir/Cortex, VictoriaMetrics, AWS AMP, Grafana Cloud, Google Managed Prometheus.

### Fixed : configuration d'infrastructure
- **`timeInterval` de la datasource aligné sur `scrape_interval`.** Grafana en dérive `$__rate_interval`, que tous les panneaux générés utilisent ; laissé vide, Grafana suppose 15 s et fausse silencieusement chaque `rate()` sur une plateforme qui scrape plus lentement.
- Compose modernisé : healthchecks sur les trois services et dépendances `service_healthy`, donc `up --wait` remplace les attentes aveugles ; ports liés à la loopback ; `no-new-privileges` ; limites mémoire ; volumes nommés ; `mem_limit` plutôt que `deploy:`, ignoré par Compose hors Swarm ; aucune image `:latest` ; multi-arch sans épinglage de plateforme.
- Datasource provisionnée non éditable, requêtes en POST.

### Added : vérification
- Porte CI : `yamllint`, `promtool check config`, et `promtool check rules` sur **les deux** formats de règles.
- Harnais section [21] : 16 invariants sur les YAML d'infrastructure.

## [1.3.0] - 2026-08-30
### Changed: the product now speaks the language of its audience
- **Generated dashboards, alerts and recording rules are English by default.**
  Every panel title, description, legend and alert summary was French: a platform
  team outside France deployed this and got `Dépense par souveraineté du fournisseur`
  on its screens. The README and SKILL.md had been translated; the artefact itself
  had not, which is the only part users actually see.
- `--locale fr` restores the French labels from `references/locale.fr.json`.
  Adding a language is a JSON file, not a code change.
- Harness section [20] fails the build if any generated artefact contains
  non-English labels again.

## [1.2.3] - 2026-08-30
### Fixed : deux défauts silencieux trouvés par des classes de test nouvelles
- **Le coût des tokens de sortie disparaissait des recording rules.** La règle joignait les deux directions avec `or`, or `A or B` ne retourne de B que les séries *absentes* de A : les deux côtés portant les mêmes labels, tout le coût de sortie était écarté : un sous-comptage d'un facteur ~6 selon le modèle, sans la moindre erreur affichée. Décomposé en `llm:cost_usd_per_second:input` / `:output` / total, avec somme tolérante aux séries manquantes. Détecté en comparant les deux chemins de calcul du coût sur données réelles.
- **Injection PromQL via les noms de modèles.** Les noms viennent de labels applicatifs ; un nom contenant un guillemet s'échappait du sélecteur regex, et cassait le YAML des recording rules. `_rx` échappe désormais la couche chaîne, les labels YAML passent par `json.dumps`, et les noms sont neutralisés dans les tableaux markdown. 60 expressions issues de noms hostiles validées par le parseur Prometheus réel.

### Added
- `tests/value_invariants.py` : vérifie que les nombres sont cohérents entre eux, pas seulement présents : quantiles ordonnés, ratios bornés, convergence des deux chemins de coût, somme des régions égale au total. Branché en CI.
- Harnais : entrées hostiles et structure des recording rules ancrées en non-régression.

## [1.2.2] - 2026-08-30
### Fixed : chemins d'export Prometheus (deux angles morts reproduits sur instance réelle)
- **Préfixe de namespace invisible.** Les regex Prometheus sont ancrées : la signature `gen_ai_.*` ne matchait pas `myapp_gen_ai_...`, produit par l'option `namespace` des exporters OTel Collector ou par un `metric_relabel_configs`. La forge annonçait « aucun signal LLM » sur une stack parfaitement instrumentée. Signatures désormais tolérantes au préfixe.
- **Noms UTF-8 non supportés.** Avec `translation_strategy: NoTranslation` (Prometheus ≥ 3.0), les noms OTel gardent leurs points (`gen_ai.client.token.usage`) et les labels aussi. Ces séries n'étaient ni découvertes, ni interrogeables : un nom pointé nu renvoie HTTP 400, il faut la syntaxe `{"nom", label="v"}`. Ajout des helpers `msel`/`qlbl`, routage de toutes les compositions métrique/label, résolveur de signaux insensible au séparateur.

### Fixed : recording rules muettes
- Les prix et le coût étaient déclarés dans **deux groupes de règles distincts**. Prometheus évalue les groupes en parallèle et décale leur démarrage : la règle de coût pouvait s'exécuter avant l'existence des prix et ne rien produire, avec `health=ok`, donc silencieusement. Un seul groupe désormais, où l'ordre séquentiel est garanti. Vérifié : 5 séries de coût matérialisées, bascule automatique en mode `recorded`.

### Verified
38/38 expressions exécutées sans erreur sur un Prometheus réel pour les trois variantes (classique, préfixée, UTF-8) ; 63/63 sur la stack de démo complète, sans régression. Tests permanents ajoutés au harnais.

## [1.2.1] - 2026-08-30
### Fixed
- **Échappement regex PromQL** (bug trouvé par le nouveau contrôle live, invisible hors ligne) : `re.escape` produisait `\-`, rejeté par RE2, et un `\.` simple était consommé par le littéral chaîne du matcher avant d'atteindre la regex. Le panel « Trafic par souveraineté » était cassé pour tout modèle contenant un tiret ou un point, c'est-à-dire presque tous.

### Added
- `tests/live_query_check.py` : sonde un vrai Prometheus, construit la capability map à partir de ce qu'il y trouve, lance la forge et **exécute chaque expression générée** (63 sur la stack de démo). Le harnais hors ligne valide la structure ; celui-ci valide la sémantique.

### Verified on real data
- 63/63 expressions renvoient des données ; recording rules auto-détectées (dialecte `recorded`) et coût basculé en O(1) : `(sum(llm:cost_usd_per_second) or vector(0)) * 86400` → 337,36 USD/jour, ventilé 🇪🇺 3,12 / 🇺🇸 329,63 / 🌏 4,61.

## [1.2.0] - 2026-08-30
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
- **Cardinalité** : garde-fou dur (aucun group-by au-delà de 300 valeurs distinctes) et bornage `topk` sur tous les panels groupés (équipes, services, agents, outils, logs) : un graphe à 300 courbes est illisible *et* lent.
- `maxDataPoints: 500` sur toutes les séries temporelles : coût de requête borné sur les longues plages.
- Visuels du README explicitement étiquetés « illustration, pas capture » ; `make demo` fournit le rendu réel.

### Changed
- SKILL.md intégralement en anglais (le déclenchement suivait mal les requêtes anglophones) ; version française conservée dans `docs/SKILL.fr.md`.
- Harnais d'audit : 27 → 41 contrôles.

## [1.1.0] - 2026-07-23
### Added
- Visual verification layer: `visual_audit.py` (native renderer + Playwright fallback, DOM pre-scan), vision checklist & remediation protocol (`references/visual_verification.md`), `deploy_manifest.json`.
- Offline audit harness: 27 checks across 4 instance topologies (`tests/audit_harness.py`).
### Fixed
- **Billing-accuracy bug**: model matcher now scores by specificity: `gpt-5.4-mini` can no longer be priced as `gpt-5.4` (was ×5.5 overcost). Regression-tested.
### Hardened
- Per-dashboard capture isolation; tolerance for hand-made capability maps.

## [1.0.0] - 2026-07-12
- Initial release: discovery-first pipeline, 6 blueprints, 4 dialects, 30-model registry (verified 2026-07-12), 5 SLO alerts, EU AI Act mapping (post-Digital-Omnibus timeline).
