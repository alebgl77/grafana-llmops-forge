# Feuille de route produit

**Chaque changement IA, une décision que vous pouvez justifier.**

Pour les responsables plateforme et ingénierie IA des entreprises européennes qui exploitent
Grafana en auto-hébergement, Forge propose de transformer la télémétrie existante en décisions
opérationnelles reproductibles. Exécution de Forge et stockage des artefacts de décision restent
dans l'infrastructure du client. Celui-ci choisit et contrôle les intégrations externes,
sans Forge Cloud obligatoire.

[Version anglaise canonique](../ROADMAP.md) · [Capacités actuelles](README.fr.md)

## Version publiée, validation sur branche et propositions

**État au 2026-09-14.** La version publiée de référence est **v2.0.2**, sortie le 2026-09-02.
Les cinq corrections de fondation et le correctif du cycle des alertes budgétaires de la
[PR nº 5](https://github.com/alebgl77/grafana-llmops-forge/pull/5) sont **validés sur sa branche
et attendent leur intégration dans main**. Ils sont implémentés dans la PR, **pas encore dans main ni dans une version publiée**.
Les contrats H0 restants, H1–H3, le parcours et le dossier de décision restent des travaux futurs proposés.

Aujourd'hui, Forge est une CLI locale fondée sur la bibliothèque standard Python et un agent skill.
La découverte alimente sept tableaux de bord Grafana, des alertes, des tarifs et règles
d'enregistrement, des exports portables et des captures visuelles. Forge utilise les instances
Prometheus/Mimir, Loki, Tempo et Grafana du client, ainsi que des évaluateurs externes.
Cette orientation conserve ce modèle : aucun serveur Forge persistant, collecteur, stockage
de traces ou moteur d'évaluation.

Les domaines existants fournissent les premiers signaux : FinOps et infrastructure auto-hébergée
pour les coûts et ressources ; Ops et agents/RAG pour la latence, les tentatives supplémentaires
et les échecs ; qualité pour les évaluations externes. L'adoption peut délimiter les usages réels
et cohortes lorsque des identifiants existent ; la gouvernance apporte faits déclarés ou observés
et inconnues. Leur rapprochement en une comparaison valide reste un travail futur :
ce n'est pas une capacité revendiquée pour les sept tableaux de bord actuels.

## Un parcours futur : faut-il migrer cet assistant ?

**Démonstration future illustrative, pas un parcours disponible.** Une équipe envisage de remplacer
le modèle accessible par API de son assistant RAG interne par une infrastructure d'inférence
hébergée dans l'UE. Le candidat semble moins cher par token. Cela ne suffit à établir ni un coût
inférieur par résultat utile, ni une qualité acceptable, ni le lieu de traitement de chaque dépendance.

1. Un changement de runtime altère le sens ou la couverture d'un signal de tokens. Forge
   identifierait l'écart au contrat de télémétrie et préciserait la mesure manquante avant de comparer.
2. Une fois cet écart corrigé, l'équipe comparerait référence et candidat sur un périmètre défini.
   Forge réunirait la télémétrie existante et les évaluations externes pour une charge précise,
   avec versions du modèle, du prompt et de la recherche documentaire, critères de qualité et limites de latence.
3. La revue distinguerait coûts d'usage API rapportés, estimations tarifaires, coûts d'infrastructure
   alloués, hypothèses et lieux de déploiement déclarés. Échecs ou tentatives supplémentaires pourraient
   annuler l'avantage tarifaire ; une allocation incomplète pourrait laisser la réponse indéterminée.
4. La conclusion serait **comparable et favorable**, **comparable et défavorable**, ou
   **indéterminée**, avec ses raisons. Une conclusion indéterminée préciserait l'action minimale :
   retrouver la version d'un évaluateur, mesurer une population absente ou valider une allocation.
5. Un responsable pourrait examiner le diff de configuration, les contrôles de mise en service
   et les prérequis de retour arrière dans les outils existants, puis conserver un dossier portable.

« Ne pas déployer » et « preuves insuffisantes » sont des résultats utiles. Un écart observé
n'est pas automatiquement causé par le changement de modèle. Ce parcours ne promet ni
prédiction contrefactuelle, ni routage automatique du trafic, ni retour arrière automatique.

## Trois paris produit

**1. Des mesures interprétables même quand la plateforme évolue.**
Unités, périmètre, fraîcheur, couverture et provenance doivent accompagner chaque signal.
Des correspondances OpenTelemetry versionnées et des contrats par runtime doivent révéler
les sémantiques modifiées ou non prises en charge. Une inconnue explicite vaut mieux qu'un
chiffre précis fondé sur une hypothèse invalide.

**2. Un coût par tâche réussie réellement comparable.**
La réussite exige une définition versionnée, une évaluation externe et des critères de latence.
Il faut identifier cohortes et versions du modèle, du prompt et de la recherche documentaire.
Coûts d'usage API rapportés, estimations tarifaires, coûts d'infrastructure auto-hébergée alloués
et estimations de scénario restent distincts. Le coût de la télémétrie native n'est pas une facture ;
le rapprochement H2 vérifie périmètre, retard et résidus. Le coût inclut tentatives supplémentaires
et échecs ; les règles du dénominateur précisent les tâches éligibles et réussies. Aucun score pondéré universel.

**3. Un dossier de changement IA que l'on peut examiner.**
Le pari porte sur la validité de la comparaison et les raisons de décider à partir de plusieurs outils.
Un dossier portable rend ce raisonnement vérifiable ; un emballage JSON ne suffit pas à se distinguer.
Dépendances déclarées ou observées, évaluations et références de mise en service GitOps doivent
s'y rejoindre sans remplacer les systèmes qui les ont produites.

## Le dossier de décision proposé

**Interface proposée, ni CLI ni schéma déjà implémentés.** Le dossier serait un JSON portable
et versionné, accompagné d'une synthèse lisible et de liens vers Grafana et les éléments existants.
Il doit permettre de comprendre ce qui justifiait la décision même après l'évolution des vues en ligne.

| Partie du dossier | Ce que le responsable doit pouvoir examiner |
| --- | --- |
| Périmètre et identité | Charge/cohorte, référence et candidat, versions du modèle/prompt/recherche documentaire, fenêtres temporelles et tailles d'échantillon. |
| Éléments de mesure | Sources, unités, fraîcheur, couverture et lacunes connues ; entrées agrégées figées ou références immuables vers les éléments conservés. |
| Reproduction | Versions/empreintes des règles de décision et des calculs, liées aux versions des entrées conservées. |
| Coûts | Nature du coût, tentatives/échecs inclus, règles d'allocation, version des tarifs et résidus de rapprochement. |
| Qualité et latence | Définition versionnée de la réussite, critères, provenance/version des évaluateurs, références des exécutions externes, incertitude et seuils minimaux de preuve. |
| Dépendances | Origine du fournisseur distincte du lieu de déploiement ; chaque fait classé comme déclaré, observé ou inconnu. |
| Comparaison et contrôles | Écarts référence/candidat, validité de comparaison, résultats motivés des contrôles et prochaine mesure pour chaque conclusion indéterminée. |
| Revue et promotion | Diff de configuration, référence de l'approbateur dans les outils existants, éléments de mise en service et prérequis de retour arrière. |

Les métriques sont agrégées par défaut ; l'exploration des traces est facultative. Prompts bruts
et secrets sont exclus par défaut. Accès aux références, conservation des éléments et contrôles
d'export des données sensibles font partie du contrat : un lien ne garantit pas une preuve durable
et accessible. Un artefact signé atteste son intégrité et l'identité du signataire, pas la vérité
des faits, la résidence du déploiement ou la conformité réglementaire.

## Séquence : valider chaque horizon avant le suivant

Il s'agit de dépendances et de critères de passage, pas d'engagements calendaires. Les anciens
libellés v2.1, v2.2 et v3 restent des regroupements de livraison envisagés, à revoir après validation.

| Horizon | Question de l'utilisateur | Résultat démontrable | Dépendance |
| --- | --- | --- | --- |
| **H0 · Des fondations fiables** | Peut-on interpréter ces chiffres et voir ce qui changerait ? | Contrats des signaux, lacunes explicites et diff des ressources en lecture seule. | Intégrer la PR nº 5 validée ; établir le périmètre de mesure. |
| **H1 · Comparer un changement** | Peut-on accepter ce modèle ou prompt au niveau de qualité et de latence requis ? | Comparaison délimitée, coût par tâche réussie et conclusion motivée. | Les contrats H0 tiennent pour la charge du pilote. |
| **H2 · Livrer avec des preuves** | Un tiers peut-il examiner et reproduire la décision de promotion ? | Dossier portable de promotion et contrôles consommés par la CI existante. | H1 apporte une valeur de décision répétée. |
| **H3 · Répéter la prochaine migration** | Que tester avant de changer de fournisseur ou d'hébergement ? | Compte rendu d'une répétition exécutée ou scénario de sensibilité clairement identifié. | Les pilotes précédents justifient l'élargissement et les données comptables existent. |

### H0 · Des fondations fiables

**Résultat :** des fondations fiables pour les sept domaines et un aperçu/diff des ressources
Grafana proposées, en lecture seule, distinguant créations, mises à jour et éléments inchangés.

La PR nº 5 est le premier prérequis : intégration échantillonnée du coût enregistré avec couverture ;
numérateur et dénominateur financiers liés à la même source et budget instantané ; aucune
troncature silencieuse des modèles et couverture tarifaire explicite ; moyenne/minimum des
jauges de score distincts des quantiles d'histogramme ; origine fournisseur séparée du lieu
de déploiement déclaré et inventaire local. Ces corrections réduisent les erreurs sans établir
l'exhaustivité des données du backend.

La PR nº 5 omet aussi les nouvelles règles budgétaires lorsque la couverture financière est
insuffisante. Lors d'un déploiement avec `--with-alerts`, une alerte budgétaire Forge existante
est mise en pause après vérification de son appartenance et de son périmètre. Cette pause est
conservée si la couverture redevient suffisante.

Les contrats restants couvrent unités, sens des compteurs/histogrammes/jauges, fraîcheur,
signaux absents ou non pris en charge, modèles sans tarif et provenance. L'absence complète
de compteurs inline peut encore sembler être un zéro ; elle ne doit pas prouver l'absence de dépense.

**Passage uniquement si :** jeux de contrôle connus et captures du pilote distinguent zéro réel,
données absentes, périmées ou non prises en charge ; périmètre et couverture financiers sont
vérifiables ; les changements sémantiques OTel/runtime sont détectés ou rejetés. Des diffs répétés
restent stables et ne produisent aucune écriture. Une lacune masquée ou un désaccord financier
inexpliqué bloque H1.

### H1 · Comparer un changement

**Résultat :** une comparaison référence/candidat délimitée, avec trois conclusions possibles :
comparable et favorable, comparable et défavorable, ou indéterminée. Chacune est motivée ;
toute conclusion indéterminée précise la mesure ou l'action minimale à entreprendre.

Commencer par le coût d'usage API rapporté par la télémétrie native d'une charge RAG/assistant, en important
les évaluations existantes. Ajouter un runtime auto-hébergé après avoir démontré l'utilité du parcours ;
coûts estimés et coûts d'infrastructure alloués exigent une provenance validée séparément.
Comparer des cohortes compatibles avec un périmètre de coût et un dénominateur explicites,
incluant tentatives supplémentaires et échecs. Analyser économie du cache et consommation
du budget seulement lorsque les usages et tarifs nécessaires sont observables.

**Passage uniquement si :** le pilote reproduit la comparaison à partir de ses données et rejette
cohortes, fenêtres, définitions de réussite ou couvertures de coût incompatibles. Taille d'échantillon,
incertitude et provenance des évaluateurs satisfont des seuils minimaux déclarés ; une moyenne
de qualité seule ne suffit pas. Signaux absents, échantillon insuffisant ou évaluation instable
conduisent à des preuves insuffisantes. Un écart favorable observé ne prouve pas un effet causal du modèle.

### H2 · Livrer avec des preuves

**Résultat :** le dossier portable de promotion et les contrôles consommés par la CI existante,
avec séparation de la revue, du plan et de l'application pour JSON portable, Terraform et
provisioning natif. Le plan n'écrit rien. Les outils du client gardent approbation, déploiement
et retour arrière ; Forge apporte preuves et contrôles, avec les privilèges minimaux et sans
nouvelle boucle de contrôle en arrière-plan.

Le JSON classique reste le chemin de compatibilité. Une future option schema-v2 exige une
activation explicite sur les parcs Grafana adaptés et des preuves de compatibilité pour l'import,
la mise à niveau et le retour arrière. L'attribution par trace/conversation peut utiliser exemplars
et références Tempo existants, sans placer leurs identifiants dans les labels de métriques.

Les adaptateurs d'usage fournisseur sont facultatifs et suivent des contrats explicites sur les
permissions, quotas, stockage, conservation et rapprochement. Attribution par trace et rapprochement
fournisseur doivent exposer exhaustivité, retard et résidus non alloués, sans suggérer des totaux complets.

**Passage uniquement si :** un autre responsable rejoue la décision avec les entrées et règles
versionnées conservées. Des éléments modifiés ou absents rendent la conclusion indéterminée,
sans réutiliser le verdict antérieur. Masquage et accès sont contrôlés ; le plan n'écrit rien ; l'approbation reste
dans la CI du client. Un jeu de contrôle maîtrisé éprouve les prérequis de retour arrière via les
outils existants. L'attribution incomplète reste visible et les combinaisons de schémas non prises
en charge échouent explicitement. Aucun contrôleur de déploiement n'est nécessaire pour passer.

### H3 · Répéter la prochaine migration — exploration

**Résultat :** inventaire des dépendances, endpoints observés lorsqu'ils sont disponibles et
exercice délimité de migration fournisseur ou hébergement. Distinguer une **répétition exécutée**,
avec mécanisme de test et preuves, d'un **scénario de sensibilité** aux plages d'entrées et
hypothèses visibles. Capacité, sensibilité du coût total et résultats d'évaluation comparative
de qualité pourraient orienter le prochain test.

**Passage uniquement si :** le pilote rattache chaque conclusion à un test exécuté ou une
hypothèse explicite, reproduit les calculs de scénario et identifie les entrées susceptibles de
changer la décision. Dépendances et lieux inconnus le restent. Arrêter l'élargissement si le
parcours précédent n'est pas réutilisé ou si les données comptables ne permettent pas l'analyse.

Cet horizon n'est ni une prévision causale, ni une attestation juridique de résidence, ni un routeur automatique.

## Valider la direction par un pilote progressif

Le premier pilote proposé demande : **« Peut-on accepter ce changement de modèle ou de prompt
à la qualité et à la latence requises, et combien coûte une tâche réussie ? »**
Commencer par une charge RAG/assistant utilisant une API ; envisager ensuite un runtime
auto-hébergé. Il s'agit d'une validation par étapes, pas d'un engagement à livrer les deux simultanément.

Mesurer une référence avant de fixer des objectifs d'amélioration :

- Délai entre changement éligible et décision examinable, collecte des éléments comprise.
- Part des changements éligibles avec preuves reproductibles ; définir l'éligibilité au départ.
- Couverture des signaux, écarts de rapprochement et inconnues non résolues.
- Coût par tâche réussie à critères de qualité et latence fixes, avec provenance des coûts.
- Réutilisation du parcours par l'équipe pour un deuxième changement réel.

**Poursuivre ou arrêter :** le pilote reproduit une décision depuis le dossier exporté, refuse
correctement de comparer des éléments absents ou incompatibles et réutilise le parcours pour
un deuxième changement réel. Fixer les seuils avec le pilote après mesure de référence, sans
annoncer de gain en pourcentage. Reporter ou arrêter un pari si un outil natif répond déjà au
besoin, si un nouveau stockage obligatoire domine le travail ou si les éléments ne permettent pas de décider.

## Positionnement

Descriptions officielles vérifiées le **2026-09-08** ; ces repères ne constituent pas une
comparaison exhaustive des fonctionnalités.

| Capacité existante | Conséquence pour l'orientation proposée de Forge |
| --- | --- |
| [Grafana Cloud Agent Observability](https://grafana.com/docs/grafana-cloud/observe-and-act/agent-observability/) couvre traces OTel, coûts, latence, évaluations/gardes en ligne et expériences hors ligne. | Réutiliser les éléments et Grafana ; ne pas reconstruire un backend d'observabilité des agents. |
| [Grafana Assistant](https://grafana.com/products/cloud/ai-assistant/) prend en charge OSS/Enterprise auto-gérés via une connexion à Grafana Cloud. | Un assistant générique n'est pas le pari produit. |
| Le [serveur MCP open source de Grafana](https://grafana.com/docs/grafana/latest/developer-resources/mcp/) prend en charge Grafana auto-géré et Cloud. | L'accès MCP ou le CRUD des tableaux de bord ne suffit pas à se distinguer. |
| [Langfuse](https://langfuse.com/resources/engineering/clarifications) propose traces, prompts, datasets, évaluations et expériences, avec auto-hébergement et workflows CI. | Importer les évaluations ; ne pas revendiquer l'exclusivité des contrôles CI génériques. |
| [Phoenix](https://arize.com/phoenix/) propose traçage, évaluations et expériences. | Travailler avec les évaluateurs et systèmes de traces existants. |

**Hypothèse à valider :** des décisions opérationnelles reproductibles entre outils, sur la
plateforme auto-hébergée existante du client, justifient une adoption répétée. La validité des
comparaisons, le refus explicite et les lacunes accompagnées d'une action doivent le démontrer ;
ce n'est ni une revendication d'exclusivité, ni une raison de remplacer Grafana, un moteur
d'évaluation ou un backend de traces.

## Maintenance et hypothèses ouvertes

Fraîcheur/provenance des tarifs, correspondances OTel/runtime, terminologie de gouvernance,
compatibilité, sécurité, intégrité de la chaîne de distribution et documentation cohérente
restent des prérequis à chaque horizon. Les captures visuelles facilitent la revue ;
elles n'établissent ni la vérité ni l'exhaustivité de la télémétrie.

Accès au pilote, définition stable de la réussite, qualité des évaluations, données comptables
et autorisations d'utilisation/export restent à confirmer. Équipe et dates de livraison ne sont
pas établies. Périmètre et numéros de version suivent les critères validés, pas ce document.
