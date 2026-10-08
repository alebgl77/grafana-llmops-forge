# Provenance des prix

Le registre livré reste la source hors ligne et ne contient aucune valeur
Artificial Analysis. Le fallback tiers est désactivé par défaut.

## Revue du seed officiel — 2026-10-08

Les 33 entrées ont été revues sur les sources officielles : 24 portent un tarif
officiel et 9 restent indisponibles. Les IDs et leur ordre sont conservés ;
`verified_at`, `pricing_verified_at` ou `availability_checked_at` indiquent cette
revue. Cette maintenance du seed est distincte du rafraîchissement local effectué
pendant une exécution de la forge. Un prix `null` reste inconnu ; les zéros de
GLM-4.7-Flash restent des tarifs gratuits publiés.

Les seuls changements de prix sont GLM-5.2, désormais publié à **1,40 / 4,40 /
0,26 USD** par million de tokens input / output / lecture de cache, avec un
contexte de 1000000 tokens, et l'ajout du cache READ de Nova Lite à **0,015 USD**
par million. Tous les autres prix et les tiers longs existants sont conservés.

Pour Nova Lite, le [catalogue régional AWS Bedrock](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json)
est en version `20261006144726`, publié le `2026-10-06T14:47:26Z`, avec effet au
`2026-10-01`. Le périmètre est `Nova Lite`, `On-demand Inference`,
`regionCode=us-east-1` (N. Virginia), synchrone standard. Les trois dimensions
sont exprimées par 1000 tokens ; la conversion en prix par million multiplie
chaque montant par 1000 :

| Dimension | SKU | USD / 1000 tokens | USD / million |
| --- | --- | ---: | ---: |
| Input | `QRGWJ3P8FT28EYX2` | 0,000060 | 0,06 |
| Output | `CBZ6A6U7XK8WJ3KA` | 0,000240 | 0,24 |
| Cache READ | `FYTFBAWEJFBAVTWK` | 0,000015 | 0,015 |

Aucun tarif de cache WRITE n'est ajouté. Les prix sont en USD, standard
non-batch, hors remises volume, avec les limites de périmètre suivantes :

| Fournisseur | Sources exactes revues et périmètre |
| --- | --- |
| OpenAI | [Tarification](https://developers.openai.com/api/docs/pricing), fiches [GPT-5.5](https://developers.openai.com/api/docs/models/gpt-5.5), [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4), [GPT-5.4-mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [GPT-5.4-pro](https://developers.openai.com/api/docs/models/gpt-5.4-pro), [GPT-4.1](https://developers.openai.com/api/docs/models/gpt-4.1), [GPT-4.1-nano](https://developers.openai.com/api/docs/models/gpt-4.1-nano) et [o4-mini](https://developers.openai.com/api/docs/models/o4-mini). Tiers longs existants de 5.5, 5.4 et 5.4-pro au-delà de 272000 tokens input conservés ; aucun prix de cache long non publié n'est inventé. Nano et o4-mini restent tarifés, avec arrêt annoncé au 2026-10-23 dans les [dépréciations](https://developers.openai.com/api/docs/deprecations). |
| Anthropic | [Tarification](https://platform.claude.com/docs/en/about-claude/pricing), [Fable 5](https://platform.claude.com/docs/en/models/fable-5/overview), [Opus 4.8](https://platform.claude.com/docs/en/models/opus-4-8/overview), [Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview), [Sonnet 5](https://platform.claude.com/docs/en/models/sonnet-5/overview) et [Haiku 4.5](https://platform.claude.com/docs/en/models/haiku-4-5/overview). Tarifs API standard et cache en lecture ; modèles legacy encore actifs. La mention historique de contrôle export de Fable, non étayée, est supprimée. |
| Google | [Gemini 3.1 Pro Preview](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-pro-preview), [3 Flash Preview](https://ai.google.dev/gemini-api/docs/pricing#gemini-3-flash-preview), [3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-lite) et [2.5 Flash](https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash). Pro couvre toutes les modalités input/cache ; Flash couvre texte/image/vidéo, sans les tarifs audio input/cache plus élevés. Le stockage du cache est exclu. 2.5 Flash reste servi aux utilisateurs existants selon les [dépréciations](https://ai.google.dev/gemini-api/docs/deprecations). |
| Mistral | [Prix de Large 3](https://docs.mistral.ai/inference/pricing). [Medium 3](https://docs.mistral.ai/models/mistral-medium-3-25-05) est déprécié le 2026-05-22, [Small 3.2](https://docs.mistral.ai/models/mistral-small-3-2-25-06) le 2026-04-30. [Magistral Medium](https://docs.mistral.ai/models/magistral-medium-1-2-25-09) et [Small](https://docs.mistral.ai/models/magistral-small-1-2-25-09) sont dépréciés ; l'ID générique reste ambigu. Les trois entrées indisponibles conservent `null`, sans assimiler dépréciation et retrait. |
| xAI | [Retrait du 15 mai](https://docs.x.ai/developers/migration/may-15-retirement) : les variantes Grok 4 et 4 Fast sont retirées au 2026-05-15 et routées vers Grok 4.3, au tarif différent. Les deux entrées restent `null`. |
| Meta | [Présentation officielle de Llama 4](https://ai.meta.com/blog/llama-4-multimodal-intelligence/) : poids téléchargeables et partenaires d'hébergement, sans tarif universel d'API hébergée pour Maverick. |
| DeepSeek | [Prix courants](https://api-docs.deepseek.com/quick_start/pricing/) et [mises à jour](https://api-docs.deepseek.com/updates/) : v4-flash est retiré et routé vers v4.1-flash, dont les tarifs peak/off-peak ne sont pas représentables ici ; l'ID exact v4-pro-max est absent, sans équivalence établie avec pro ; v3.2 est remplacé et n'a pas de tarif direct courant. Les trois entrées restent `null`. |
| Alibaba | [Qwen3.7-Max](https://www.alibabacloud.com/help/en/model-studio/qwen3-7-max) et [Qwen3.6-Plus](https://www.alibabacloud.com/help/en/model-studio/qwen3-6-plus) : tarifs International, Singapore, avec lecture de cache **explicite**. Pour 3.7-Max, le cache implicite coûte 0,50 USD par million, contre 0,25 USD pour la lecture du cache explicite retenue ici. Le tier de 3.6-Plus au-delà de 256000 tokens est conservé. |
| Moonshot | La [page officielle Kimi](https://platform.kimi.ai/) expose K2.6 à 0,95 / 4 / 0,16 USD par million. La page canonique de documentation ne livrait pas les montants dans l'extraction consultée ; le lien du registre pointe donc vers la preuve numérique visible. Le contexte existant de 256000 tokens est conservé. |
| Z.AI | [Prix officiels](https://docs.z.ai/guides/overview/pricing) de GLM-5.2 et GLM-4.7-Flash, et [contexte de GLM-5.2](https://docs.z.ai/guides/llm/glm-5.2). GLM-5.2 passe de `unavailable` à `official`, avec une date de vérification du prix remplaçant la date de contrôle de disponibilité. |
| MiniMax | [Tarifs pay-as-you-go](https://platform.minimax.io/docs/guides/pricing-paygo) de M3 **Standard**, remise permanente de 50 % déjà incluse ; Priority à 1,5 fois ce tarif exclu. La source indique « 512k » : le seuil existant de 512000 tokens est conservé sans affirmer une base 1024. |

Les alias `qwen-max` et `qwen-plus` sont retirés uniquement des entrées
`qwen3.7-max` et `qwen3.6-plus` : les fiches officielles décrivent des identités
distinctes, [Qwen-Max](https://www.alibabacloud.com/help/en/model-studio/qwen-max)
(1,60 / 6,40 USD, contexte 32768) et
[Qwen-Plus](https://www.alibabacloud.com/help/en/model-studio/qwen-plus)
(0,40 / 1,20 USD sans thinking, output 4 USD avec thinking, jusqu'à 256k).
Aucune nouvelle entrée n'est ajoutée. Les autres raccourcis sont conservés pour
compatibilité ; cela ne certifie pas leur statut d'alias officiel.

Le schéma reste limité à un prix de base et un seul tier long, avec la lecture
du cache lorsqu'elle est publiée. Ces tarifs ne garantissent pas une
reconstitution complète d'une facture fournisseur : modalités, région de
déploiement, stockage, écritures de cache, routage et options commerciales
doivent correspondre au périmètre documenté.

## Identité des modèles du registre

Les IDs et alias sont comparés exactement après normalisation alphanumérique
en minuscules. Un suffixe séparé par `-` ou `_`, au format `YYYYMMDD` ou
`YYYY-MM-DD` et représentant une date valide, peut reprendre le tarif d'un
ID/alias exact sans suffixe. Un ID daté explicitement présent reste prioritaire.
Aucun préfixe fournisseur, nom de déploiement ou variante libre ne suffit :
`my-gpt-5.4-production`, `gpt-4` et `gpt-5.4-turbo` restent inconnus tant qu'un
alias explicite n'est pas fourni. Toute égalité entre plusieurs entrées est refusée.
Cette compatibilité de nom daté ne certifie pas l'équivalence du tarif fournisseur.

## Activation et secret

L'activation exige les deux éléments suivants:

```bash
export ARTIFICIAL_ANALYSIS_API_KEY="..."
python3 scripts/forge_dashboards.py --capability capability_map.json \
  --pricing-fallback artificial-analysis
```

La forge n'accepte aucun autre nom de variable ou argument de clé. La valeur
sert uniquement à l'en-tête `x-api-key`; elle n'est ni affichée, ni placée dans
une URL, ni écrite dans un fichier.

## Requête et dégradation

La seule API appelée est `GET
https://artificialanalysis.ai/api/v2/language/models/free`, avec `page=N` pour
la pagination. Les délais, pages, modèles et octets sont bornés. Une redirection
vers une autre origine est refusée. Aucun appel n'a lieu si tous les modèles
détectés ont déjà un tarif complet ou si un cache frais les couvre.

Un modèle n'est accepté que si sa valeur observée correspond exactement, après
normalisation alphanumérique en minuscules, à un unique `id`, `slug`, `name` ou
alias. Une ambiguïté, une absence, un prix input/output null, un JSON invalide,
un HTTP 401, 403, 429 ou 5xx laisse le modèle non tarifé. La forge continue.

## Sémantique et cache

Les valeurs retenues sont des estimations médianes multi-provider. Chaque
entrée porte `pricing_source_kind: artificial_analysis`, l'URL source, un
horodatage ISO UTC, `pricing_basis: median_multi_provider`, `estimate: true` et
l'attribution `Artificial Analysis`. Un tarif officiel complet reste
prioritaire.

L'overlay `model_registry.artificial-analysis.cache.json` est écrit atomiquement
près de la capability map et est frais 24 heures par défaut. Il contient
uniquement les entrées AA retenues, leur provenance et l'empreinte du registre
officiel utilisé comme base, jamais le registre fusionné. La base est toujours
`--registry`, un éventuel `model_registry.local.json` officiel, ou le seed
livré. La durée est ajustable avec `--pricing-cache-max-age-hours`. Un overlay
expiré, falsifié, ambigu, lié à une autre base ou illisible est ignoré entrée
par entrée sans arrêter la forge. Cet overlay est exclu du paquet `.skill` et
du SBOM; seules les sources du mécanisme sont distribuées.
