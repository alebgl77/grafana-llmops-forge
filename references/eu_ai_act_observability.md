# EU AI Act × observabilité : repères vérifiés le 8 novembre 2026

Support à la revue, sans avis juridique. L'AI Omnibus est entré en vigueur le
27 juillet 2026. Les échéances dépendent du rôle, du système et des exceptions.
Vérifier le texte applicable avant toute décision ; un dashboard ne certifie
ni une rétention effective ni la conformité.

## 1. Repères d'application

| Date | Repère | Limite |
|---|---|---|
| 2 février 2025 | Dispositions générales et interdictions initiales | Lire avec les modifications ultérieures |
| 2 août 2025 | GPAI et gouvernance | Fournisseurs concernés |
| 2 août 2026 | Transparence et contrôle des dispositions applicables | Pas une activation simultanée de toutes les règles |
| 2 décembre 2026 | Transition Art. 50(2) pour certains systèmes déjà sur le marché ; nouvelles interdictions | Pas un report général de la transparence |
| 2 décembre 2027 | Haut risque Annexe III | Champ à qualifier |
| 2 août 2028 | Haut risque intégré aux produits réglementés | Vérifier les règles sectorielles |

Sources officielles : [Commission européenne](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai),
[entrée en vigueur de l'AI Omnibus](https://digital-strategy.ec.europa.eu/en/news/ai-omnibus-enters-force),
[calendrier du Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/eu-ai-act-implementation-timeline).

## 2. Mapping articles → signaux → panels

| Article | Exigence | Signal mesurable | Panel forge |
|---|---|---|---|
| Art. 12 | Journalisation automatique des systèmes haut risque | Volume de logs par système, continuité (pas de trous) | governance › « Preuve de journalisation » |
| Art. 26§6 | Déployeur conserve les logs ≥ 6 mois | Politique de rétention couvrant la durée calendaire applicable + contrôle effectif du backend | description du panel + audit config |
| Art. 14 | Supervision humaine effective | Compteur d'interventions/overrides humains (à instrumenter côté app) | extension governance (§ blueprints) |
| Art. 50§1 | Information « vous parlez à une IA » | Compteur de disclosures affichées | extension governance |
| Art. 72 | Surveillance post-commercialisation | Dérive perf : taux d'erreur, latence, mix modèles dans le temps | gateway + adoption |
| Art. 73 | Signalement des incidents graves (délais courts : jusqu'à 15 jours, 2 jours si infrastructure critique, selon gravité) | Alertes firing + horodatage | governance › alertlist + alertes forge |
| Art. 4 | Maîtrise de l'IA par le personnel | Adoption par équipe (proxy de diffusion) | adoption |
| GPAI Art. 53 | Le fournisseur documente ; le déployeur sait ce qu'il consomme | Inventaire modèles observés × registre (région, licence, GPAI) | governance › inventaire |

## 3. Checklist déployeur (à restituer à l'utilisateur)

1. **Cartographier** : le dashboard adoption vous donne la carte des usages *observés*
   (souvent ≠ carte déclarée ; la shadow AI apparaît dans les métriques).
2. **Qualifier** : quels usages tombent en Annexe III ? (RH, crédit, scoring…)
   → échéance déc. 2027, mais les contrats clients l'exigent souvent déjà.
3. **Journaliser** : Loki + rétention 6 mois minimum sur les systèmes concernés.
4. **Superviser** : définir qui peut arrêter le système ; instrumenter les
   overrides humains.
5. **Surveiller** : alertes forge = base de la détection d'incidents Art. 73 ;
   documenter la procédure de signalement (qui, quoi, délai).
6. **Prouver** : le dashboard governance est votre pièce d'audit vivante ;
   l'exporter en PDF à date pour le comité risques.

## 4. Notes de fiabilité

- Le report Annexe III (déc. 2027) vient d'un **accord provisoire** : jusqu'à
  l'adoption formelle, le 2 août 2026 reste juridiquement la date de référence
  pour la transparence et l'activation des sanctions. En cas d'enjeu,
  re-vérifier l'état d'adoption de l'Omnibus par recherche web.
- Fine-tuning : un déployeur ne devient fournisseur GPAI que si sa modification
  dépasse ~1/3 du compute d'entraînement d'origine ; la quasi-totalité des
  fine-tunings d'entreprise reste sous le seuil.
- RGPD et AI Act s'appliquent simultanément dès qu'il y a données personnelles
  (d'où : jamais de contenu de prompt en clair dans la télémétrie).
