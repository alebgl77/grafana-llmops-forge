# Guide d'instrumentation — combler les gaps de la capability map

Ordre recommandé par ratio valeur/effort. Chaque section = un gap type détecté
par `discover.py`. Donner à l'utilisateur les configs exactes ci-dessous, pas
des généralités.

## 0. Prérequis : un backend métriques branché à Grafana

Sans datasource Prometheus/Mimir : installer Prometheus (ou Grafana Alloy →
Mimir/Grafana Cloud), puis déclarer la datasource dans Grafana
(Connections → Data sources). C'est le socle de tout le reste.

## 1. LiteLLM en passerelle — le spend en 30 minutes (valeur max / effort min)

Placer LiteLLM devant les providers donne immédiatement : spend USD natif,
tokens, latences, rate-limits restants, par équipe/clé/modèle.

```yaml
# litellm_config.yaml
model_list:
  - model_name: gpt-5.4
    litellm_params: {model: openai/gpt-5.4, api_key: os.environ/OPENAI_API_KEY}
  - model_name: claude-sonnet-4.6
    litellm_params: {model: anthropic/claude-sonnet-4-6, api_key: os.environ/ANTHROPIC_API_KEY}
  - model_name: mistral-small-3.2
    litellm_params: {model: mistral/mistral-small-3.2, api_key: os.environ/MISTRAL_API_KEY}
litellm_settings:
  callbacks: ["prometheus"]     # expose /metrics sur le port du proxy
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

Scrape Prometheus :

```yaml
scrape_configs:
  - job_name: litellm
    static_configs: [{targets: ["litellm:4000"]}]
```

Relancer `discover.py` → dialecte `litellm` détecté → blueprints finops/gateway/
adoption complets. Note : sur certaines versions, l'endpoint métriques détaillé
est une fonctionnalité enterprise ; vérifier la doc de votre version.

## 2. OTel GenAI dans les applications — traces agents & granularité fine

Python (OpenAI SDK ; équivalents Anthropic/Bedrock via OpenLLMetry/openinference) :

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp \
            opentelemetry-instrumentation-openai-v2
export OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental  # conventions récentes
export OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4317
export OTEL_SERVICE_NAME=mon-app-ia
export OTEL_METRICS_EXPORTER=otlp OTEL_TRACES_EXPORTER=otlp
opentelemetry-instrument python app.py
```

Collecteur (Grafana Alloy ou OTel Collector) → Mimir (métriques) + Tempo
(traces) + Loki (logs). Squelette OTel Collector :

```yaml
receivers: {otlp: {protocols: {grpc: {endpoint: 0.0.0.0:4317}}}}
processors: {batch: {}}
exporters:
  prometheusremotewrite: {endpoint: http://mimir:9009/api/v1/push}
  otlp/tempo: {endpoint: tempo:4317, tls: {insecure: true}}
service:
  pipelines:
    metrics: {receivers: [otlp], processors: [batch], exporters: [prometheusremotewrite]}
    traces:  {receivers: [otlp], processors: [batch], exporters: [otlp/tempo]}
```

**Contenu des prompts** : `gen_ai.input.messages` / `gen_ai.output.messages` ne
sont PAS capturés par défaut — et c'est le bon défaut (données sensibles,
RGPD). Si besoin de debug : opt-in temporaire, environnement de dev, rétention
courte, jamais vers un backend partagé. Le pattern propre en production :
payloads chiffrés dans un stockage externe, référence dans le span.

Les conventions GenAI sont en statut *Development* (v1.4x) : figer la version
d'instrumentation dans vos requirements et re-lancer `discover.py` après toute
montée de version (les noms peuvent bouger — la forge s'adapte, pas les
dashboards faits main).

## 3. Fallback sans code : OpenLIT

Si modifier les apps est trop lourd : `pip install openlit` puis
`openlit.init()` au démarrage — auto-instrumente la plupart des SDK LLM et
émet en conventions `gen_ai.*` compatibles avec le dialecte `otel_genai`.

## 4. vLLM / TGI — inference self-hosted

vLLM expose `/metrics` nativement (préfixe `vllm:`). Scrape :

```yaml
  - job_name: vllm
    static_configs: [{targets: ["vllm-0:8000", "vllm-1:8000"]}]
```

TGI : `/metrics` natif également (`tgi_*`). Ollama : exporter communautaire
requis. Multi-réplicas vLLM : garder le label `instance` pour le débit par
réplique.

## 5. GPU — dcgm-exporter (NVIDIA)

```bash
docker run -d --gpus all --rm -p 9400:9400 nvcr.io/nvidia/k8s/dcgm-exporter:latest
# K8s : helm install dcgm gpu-helm-charts/dcgm-exporter
```

Scrape le port 9400 → dialecte `gpu_dcgm` → panels GPU du blueprint inference.

## 6. Loki — preuves AI Act

Rétention déployeur ≥ 6 mois (Art. 26§6) :

```yaml
limits_config:
  retention_period: 4392h   # ~6 mois ; compactor requis pour l'appliquer
```

Envoyer les logs applicatifs IA avec un label `service_name` stable. Ne jamais
logger le contenu des prompts en clair dans Loki (mêmes précautions que §2).

## 6b. Le chemin d'export change les noms — et donc la découverte

Le même code instrumenté produit des noms différents selon l'exporter. Trois cas
vérifiés sur instance réelle, tous supportés par la forge :

| Configuration | Nom obtenu | Conséquence |
|---|---|---|
| défaut (`UnderscoreEscapingWithSuffixes`) | `gen_ai_client_token_usage_token_sum` | cas nominal |
| option `namespace: myapp` de l'exporter | `myapp_gen_ai_client_...` | les regex Prometheus étant **ancrées**, une signature `gen_ai_.*` ne matche pas — la découverte annoncerait « aucun signal » sur une stack correctement instrumentée |
| `translation_strategy: NoTranslation` (Prometheus ≥ 3.0) | `gen_ai.client.token.usage_sum`, labels `gen_ai.request.model` | les points sont conservés ; interroger ces séries exige la syntaxe `{"nom.pointé", label="v"}` — un nom nu renvoie HTTP 400 |

Côté Prometheus, l'ingestion UTF-8 suppose `global.metric_name_validation_scheme: utf8`
et un exporter qui annonce `Content-Type: ...; escaping=allow-utf-8`.

Si vous avez le choix, restez sur le nommage par défaut : c'est le mieux outillé
de l'écosystème. Si votre plateforme impose un préfixe ou le mode UTF-8, la forge
s'y adapte sans configuration — mais vérifiez que `discover.py` liste bien le
dialecte attendu avant de générer.

## 7. Vérification de bout en bout

```bash
python3 scripts/discover.py --out capability_map.json   # les gaps ont disparu ?
python3 scripts/forge_dashboards.py --capability capability_map.json --blueprints auto --deploy --with-alerts
```

Un signal apparu = des panels en plus au prochain run. C'est le contrat de la
forge : l'instrumentation progresse, les dashboards suivent.
