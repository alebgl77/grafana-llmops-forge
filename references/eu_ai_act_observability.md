# EU AI Act × Observabilité — état vérifié le 12 juillet 2026

Support d'aide à la conformité pour DSI. **Ne constitue pas un avis juridique**
— toujours le rappeler à l'utilisateur. Règlement UE 2024/1689, modifié par le
paquet Digital Omnibus (accord provisoire Conseil/Parlement du 7 mai 2026,
adoption formelle en cours au moment de la vérification — re-vérifier via web
search si la question est critique).

## 1. Calendrier applicable

| Date | Obligation | Impact observabilité |
|---|---|---|
| 2 fév. 2025 ✅ | Pratiques interdites (Art. 5) + maîtrise de l'IA (Art. 4) | Inventaire des usages (dashboard adoption = preuve de cartographie vivante) |
| 2 août 2025 ✅ | GPAI (Art. 51-56) : documentation, transparence, signalement | Concerne les *fournisseurs* de modèles ; le déployeur doit tracer QUELS modèles il consomme → inventaire du dashboard governance |
| **2 août 2026** | **Pouvoirs de sanction pleinement activés** ; transparence Art. 50 (chatbots doivent s'annoncer, Art. 50§1) | Compteur de disclosure si instrumenté ; à défaut, documentation produit |
| 2 déc. 2026 | Marquage machine-réadable des contenus synthétiques (Art. 50§2, reporté par l'Omnibus) | Journaliser la pose du watermark côté génération |
| 2 déc. 2027 | Haut risque **Annexe III** (RH, crédit, biométrie, éducation, services essentiels, justice…) — reporté du 2 août 2026 par l'Omnibus | Journalisation Art. 12 + rétention Art. 26§6 + supervision humaine Art. 14 : tout le dashboard governance |
| 2 août 2028 | Haut risque intégré à des produits réglementés (Annexe I) | Idem, périmètre produits |
| 31 déc. 2030 | Systèmes mis sur le marché avant l'échéance : fin du sursis | — |

Sanctions : 35 M€ / 7 % CA (pratiques interdites), 15 M€ / 3 % (haut risque),
7,5 M€ / 1 % (informations incorrectes). Plafonds adaptés PME.

## 2. Mapping articles → signaux → panels

| Article | Exigence | Signal mesurable | Panel forge |
|---|---|---|---|
| Art. 12 | Journalisation automatique des systèmes haut risque | Volume de logs par système, continuité (pas de trous) | governance › « Preuve de journalisation » |
| Art. 26§6 | Déployeur conserve les logs ≥ 6 mois | `retention_period ≥ 4392h` (config Loki) + ancienneté des logs | description du panel + audit config |
| Art. 14 | Supervision humaine effective | Compteur d'interventions/overrides humains (à instrumenter côté app) | extension governance (§ blueprints) |
| Art. 50§1 | Information « vous parlez à une IA » | Compteur de disclosures affichées | extension governance |
| Art. 72 | Surveillance post-commercialisation | Dérive perf : taux d'erreur, latence, mix modèles dans le temps | gateway + adoption |
| Art. 73 | Signalement des incidents graves (délais courts : jusqu'à 15 jours, 2 jours si infrastructure critique, selon gravité) | Alertes firing + horodatage | governance › alertlist + alertes forge |
| Art. 4 | Maîtrise de l'IA par le personnel | Adoption par équipe (proxy de diffusion) | adoption |
| GPAI Art. 53 | Le fournisseur documente ; le déployeur sait ce qu'il consomme | Inventaire modèles observés × registre (région, licence, GPAI) | governance › inventaire |

## 3. Checklist déployeur (à restituer à l'utilisateur)

1. **Cartographier** : le dashboard adoption vous donne la carte *réelle*
   (souvent ≠ carte déclarée — la shadow AI apparaît dans les métriques).
2. **Qualifier** : quels usages tombent en Annexe III ? (RH, crédit, scoring…)
   → échéance déc. 2027, mais les contrats clients l'exigent souvent déjà.
3. **Journaliser** : Loki + rétention 6 mois minimum sur les systèmes concernés.
4. **Superviser** : définir qui peut arrêter le système ; instrumenter les
   overrides humains.
5. **Surveiller** : alertes forge = base de la détection d'incidents Art. 73 ;
   documenter la procédure de signalement (qui, quoi, délai).
6. **Prouver** : le dashboard governance est votre pièce d'audit vivante —
   l'exporter en PDF à date pour le comité risques.

## 4. Notes de fiabilité

- Le report Annexe III (déc. 2027) vient d'un **accord provisoire** : jusqu'à
  l'adoption formelle, le 2 août 2026 reste juridiquement la date de référence
  pour la transparence et l'activation des sanctions. En cas d'enjeu,
  re-vérifier l'état d'adoption de l'Omnibus par recherche web.
- Fine-tuning : un déployeur ne devient fournisseur GPAI que si sa modification
  dépasse ~1/3 du compute d'entraînement d'origine — la quasi-totalité des
  fine-tunings d'entreprise reste sous le seuil.
- RGPD et AI Act s'appliquent simultanément dès qu'il y a données personnelles
  (d'où : jamais de contenu de prompt en clair dans la télémétrie).
