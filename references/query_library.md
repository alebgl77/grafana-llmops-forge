# Bibliothèque de requêtes : PromQL / LogQL / TraceQL par dialecte

Requêtes prêtes à coller dans de nouveaux panels. Convention : remplacer les noms
de métriques par les **noms réels** de la capability map (les suffixes d'unité
varient selon l'exporter). `$__rate_interval` partout, jamais de fenêtre en dur.

## Sommaire
1. [OTel GenAI (gen_ai_*)](#otel)
2. [LiteLLM (litellm_*)](#litellm)
3. [vLLM (vllm:*)](#vllm)
4. [GPU DCGM](#gpu)
5. [LogQL : AI Act & debug](#logql)
6. [TraceQL : agents & RAG](#traceql)
7. [Anti-patterns](#antipatterns)

<a name="otel"></a>
## 1. OTel GenAI

Histogrammes de référence (noms Prometheus typiques) :
`gen_ai_client_operation_duration_seconds_{bucket,sum,count}`,
`gen_ai_client_token_usage_token_{bucket,sum,count}` (parfois `_tokens_`),
`gen_ai_server_time_to_first_token_seconds_*`, `gen_ai_server_time_per_output_token_seconds_*`.
Labels : `gen_ai_request_model`, `gen_ai_provider_name`, `gen_ai_operation_name`
(chat | embeddings | invoke_agent | execute_tool | create_agent),
`gen_ai_token_type` (input | output), `gen_ai_agent_name`, `gen_ai_tool_name`, `error_type`.

```promql
# Débit par modèle
sum by(gen_ai_request_model)(rate(gen_ai_client_operation_duration_seconds_count[$__rate_interval]))

# Taux d'erreur global (ratio)
sum(rate(gen_ai_client_operation_duration_seconds_count{error_type!=""}[$__rate_interval]))
/ clamp_min(sum(rate(gen_ai_client_operation_duration_seconds_count[$__rate_interval])), 1e-9)

# Latence p95 par provider
histogram_quantile(0.95, sum by(le, gen_ai_provider_name)
  (rate(gen_ai_client_operation_duration_seconds_bucket[$__rate_interval])))

# Tokens output/s par modèle
sum by(gen_ai_request_model)(rate(gen_ai_client_token_usage_token_sum{gen_ai_token_type="output"}[$__rate_interval]))

# Taille moyenne de prompt (tokens/appel) : détecte la dérive de contexte
sum(rate(gen_ai_client_token_usage_token_sum{gen_ai_token_type="input"}[$__rate_interval]))
/ clamp_min(sum(rate(gen_ai_client_token_usage_token_count{gen_ai_token_type="input"}[$__rate_interval])), 1e-9)

# Coût USD/s d'un modèle précis (prix registre : input 2.5$/M, output 15$/M)
(sum(rate(gen_ai_client_token_usage_token_sum{gen_ai_token_type="input",gen_ai_request_model="gpt-5.4"}[$__rate_interval])) or vector(0)) * 2.5e-6
+ (sum(rate(gen_ai_client_token_usage_token_sum{gen_ai_token_type="output",gen_ai_request_model="gpt-5.4"}[$__rate_interval])) or vector(0)) * 15e-6

# Ratio raisonnement : part du trafic sur modèles "reasoning" (regex à adapter)
sum(rate(gen_ai_client_operation_duration_seconds_count{gen_ai_request_model=~"o4.*|gpt-5.5.*|.*opus.*"}[$__rate_interval]))
/ clamp_min(sum(rate(gen_ai_client_operation_duration_seconds_count[$__rate_interval])), 1e-9)
```

<a name="litellm"></a>
## 2. LiteLLM (passerelle)

Le spend est **natif en USD** : toujours le préférer au calcul par registre.
Labels usuels : `model`, `api_provider`, `team`, `hashed_api_key`, `end_user`.

```promql
# Dépense sur la période affichée
sum(increase(litellm_spend_metric_total[$__range]))

# Dépense par équipe, USD/jour
sum by(team)(rate(litellm_spend_metric_total[$__rate_interval])) * 86400

# Taux d'échec par provider
sum by(api_provider)(rate(litellm_proxy_failed_requests_metric_total[$__rate_interval]))
/ clamp_min(sum by(api_provider)(rate(litellm_proxy_total_requests_metric_total[$__rate_interval])), 1e-9)

# Marge de rate-limit la plus serrée (anticipation throttling)
min by(api_provider)(litellm_remaining_requests_metric)

# Latence ajoutée par la passerelle (si litellm_overhead_latency_metric présent)
histogram_quantile(0.95, sum by(le)(rate(litellm_overhead_latency_metric_bucket[$__rate_interval])))
```

<a name="vllm"></a>
## 3. vLLM

Label : `model_name`. Les 4 signaux d'or : TTFT, TPOT, file d'attente, KV cache.

```promql
# TTFT p95 / TPOT p95
histogram_quantile(0.95, sum by(le)(rate(vllm:time_to_first_token_seconds_bucket[$__rate_interval])))
histogram_quantile(0.95, sum by(le)(rate(vllm:time_per_output_token_seconds_bucket[$__rate_interval])))

# Pression scheduler
sum(vllm:num_requests_waiting)            # backlog
sum(rate(vllm:num_preemptions_total[$__rate_interval]))  # recalculs KV

# Saturation KV cache (0–1)
max(vllm:gpu_cache_usage_perc)

# Débit génération, tokens/s
sum(rate(vllm:generation_tokens_total[$__rate_interval]))

# Coût interne $/1M tokens générés (coût_horaire_GPU à renseigner, ex. 8 $/h le nœud)
(8 / 3600) / clamp_min(sum(rate(vllm:generation_tokens_total[$__rate_interval])), 1) * 1e6
```

<a name="gpu"></a>
## 4. GPU (DCGM)

```promql
avg by(gpu)(DCGM_FI_DEV_GPU_UTIL)                    # utilisation %
sum by(gpu)(DCGM_FI_DEV_FB_USED)                     # VRAM MiB
sum(DCGM_FI_DEV_POWER_USAGE)                         # watts (→ coût énergie)
# Corrélation utile : superposer TTFT p95 et GPU_UTIL sur le même panel (2 axes)
```

<a name="logql"></a>
## 5. LogQL : preuves AI Act & debug

```logql
# Volume de logs par système (preuve de journalisation Art. 12)
sum by(service_name)(rate({service_name=~".+"}[$__rate_interval]))

# Erreurs LLM dans les logs applicatifs
sum by(service_name)(rate({service_name=~".+"} |= "gen_ai" |~ "(?i)error|rate.?limit|timeout" [$__rate_interval]))

# Extraction JSON : décisions avec supervision humaine (si vos apps loggent ce champ)
sum by(service_name)(count_over_time({service_name=~".+"} | json | human_review="true" [$__interval]))
```

Rétention Art. 26§6 (≥ 6 mois) : se vérifie dans la **config** Loki
(`limits_config.retention_period` ≥ `4320h`), pas par requête. La forge le
rappelle dans la description du panel.

<a name="traceql"></a>
## 6. TraceQL : agents & RAG (Tempo)

```traceql
# Workflows d'agents
{span.gen_ai.operation.name="invoke_agent"}

# Appels d'outils lents (> 2 s)
{span.gen_ai.operation.name="execute_tool" && duration > 2s}

# Erreurs d'un agent nommé
{span.gen_ai.agent.name="support-router" && status=error}

# Traces coûteuses (gros output)
{span.gen_ai.usage.output_tokens > 4000}

# Chaîne RAG : embeddings suivis d'un chat dans la même trace
{span.gen_ai.operation.name="embeddings"} && {span.gen_ai.operation.name="chat"}
```

<a name="antipatterns"></a>
## 7. Anti-patterns

- `by(gen_ai_conversation_id)` ou tout ID unique en série temporelle → explosion
  de cardinalité. Compter : `count(count by(label_borné)(...))`.
- Fenêtres en dur (`[5m]`) dans les panels → utiliser `$__rate_interval`.
- `sum(A) + sum(B)` où une série peut être vide → chaque terme en
  `(sum(...) or vector(0))`.
- Moyennes de latence (`_sum/_count`) pour des SLO → toujours des quantiles
  d'histogramme ; la moyenne masque la queue.
- Grouper des modèles hétérogènes dans un même quantile → un p95 mélangé
  cache la régression du gros modèle derrière le petit rapide.
