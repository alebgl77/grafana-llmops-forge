# Blueprints : spécification panel par panel

Ce document décrit l'intention de chaque dashboard généré par la forge et les
**panels optionnels** à ajouter à la main (via le code de la forge, jamais en
édition directe, le prochain run écraserait). Public : Claude au moment
d'étendre, ou un humain qui audite.

Rappel layout : grille 24 colonnes ; stats 6×5 en tête, timeseries 12×8,
tableaux/texte 12–24 de large. Chaque dashboard porte le tag `llmops-forge`.

---

## 1. `finops` : AI · Executive FinOps & Coûts

**Question à laquelle il répond** : « Combien l'IA nous coûte, où, et est-ce
que ça dérive ? » Public : DSI / FinOps / CFO.

Générés : dépense période, rythme/jour, coût moyen/requête, tokens/s,
dépense par souveraineté (🇪🇺/🇺🇸/🌏, stacked), dépense par équipe (litellm) ou
tokens input par modèle (otel), tokens output par modèle, top modèles,
liste des modèles hors registre.

Extensions utiles :
- **Cache savings** : `(rate(tokens_cached) × (prix_input − prix_cache))` :
  chiffrer ce que le prompt caching économise réellement.
- **Coût par feature produit** : si un label `app`/`feature` existe, dupliquer
  le panel « par équipe » avec ce label ; c'est le panel qui déclenche les
  arbitrages produit.
- **Budget burn-down** : stat `budget_mensuel − sum(increase(spend[30d]))`
  (budget en constante dans l'expression).
- **Prix par paliers** : pour les modèles `tiered_pricing` (ex. Gemini 3.1 Pro
  au-delà de 200K tokens de contexte), le coût composé est une estimation
  basse ; le noter dans la description du panel.

## 2. `gateway` : AI · Gateway Operations

**Question** : « Le service LLM tient-il ses SLO maintenant ? » Public : SRE/on-call.

Générés : disponibilité, req/s, latence p95, TTFT p95, req/s par modèle,
p50/p95/p99, erreurs par type, quota restant par provider (litellm) ou req/s
par provider. Variable `$model` (multi-select) sur les panels compatibles.

Extensions : burn-rate multi-fenêtres (5m/1h) pour l'erreur ; heatmap de
latence (`panel heatmap` sur les buckets) ; comparaison provider A/B après
bascule de routage ; annotations de déploiement.

## 3. `agents` : AI · Agents & RAG

**Question** : « Que font nos agents, où échouent-ils, que coûtent-ils ? »

Générés : invocations/s, appels d'outils/s, durée agent p95, erreurs outils/s,
mix d'opérations (chat/embeddings/invoke_agent/execute_tool), appels par outil,
tokens par agent, latence embeddings p95, panel traces TraceQL (si Tempo).

Extensions : profondeur moyenne de workflow (spans/trace via métriques Tempo si
`metrics-generator` activé) ; taux de tool-calls en échec par outil ; coût par
agent (composer le coût registre filtré `gen_ai_agent_name`) ; MCP :
`mcp_method_name` si vos serveurs MCP sont instrumentés.

## 4. `adoption` : AI · Adoption interne

**Question** : « Qui a réellement adopté quoi ? » Public : DSI / transformation.

Générés : entités actives, nouveaux adoptants 7j (offset), modèles distincts,
req/s total, mix de modèles stacked, trafic par équipe/service, top
consommateurs de tokens.

Extensions : rétention d'usage (entités actives semaine N ET N-1) ; part des
modèles « souverains » (regex région EU du registre) ; heures de pointe
(heatmap jour×heure via `hour()`/`day_of_week()`).

## 5. `inference` : AI · Inference self-hosted

**Question** : « Nos GPU tiennent-ils la charge, et à quel coût vs API ? »

Générés : TTFT/TPOT p95, waiting, KV cache max, latence E2E p50/95/99,
tokens/s prompt vs génération, running/waiting, préemptions/s, GPU util,
VRAM, tableau benchmark coûts API (registre).

Extensions : coût interne $/1M tokens (formule dans query_library §3) à mettre
en regard du tableau API ; c'est l'argument build-vs-buy chiffré ; débit par
réplique (`by(instance)`) ; corrélation TTFT ↔ GPU_UTIL (panel 2 axes).

## 6. `governance` : AI · Gouvernance & EU AI Act

**Question** : « Que montre-t-on à un auditeur / au comité risques ? »

Générés : calendrier réglementaire (état juillet 2026, post-Digital Omnibus),
trafic par souveraineté fournisseur, preuve de journalisation (Loki),
inventaire des modèles observés (région/licence/GPAI), liste d'alertes actives
(veille incidents Art. 73).

Extensions : compteur de décisions sous supervision humaine (si loggé, Art. 14) ;
taux de disclosure chatbot (Art. 50§1, si vos apps émettent un compteur) ;
annotation Grafana à chaque échéance réglementaire ; export PDF programmé
(Enterprise/Cloud : reporting) vers le comité conformité.

Toujours rappeler : support d'aide, **pas un avis juridique**.

---

## Conventions transverses

- UID déterministes (`det_uid`) : relancer la forge met à jour sans dupliquer.
- Aucune requête inventée : tout nom de métrique vient de la capability map.
- Panels sans signal → omis (pas de panel vide « décoratif »).
- Descriptions de panels : une phrase d'interprétation (« ≥ 0.90 = préemptions
  imminentes »), pas une paraphrase du titre.
- `time.from = now-24h`, `refresh = 1m` par défaut ; governance supporte
  `now-30d` sans surcoût (peu de séries).
