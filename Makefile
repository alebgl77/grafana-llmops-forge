SHELL := /bin/bash
GRAFANA_URL ?= http://localhost:3000
PROMETHEUS_URL ?= http://localhost:9090
export GRAFANA_URL
export GRAFANA_USER ?= admin
export GRAFANA_PASSWORD ?= admin

.PHONY: demo demo-down test selftest forge audit shots package scan rules

demo: ## Stack complète : Grafana + Prometheus + métriques LLM synthétiques, puis forge
	docker compose -f demo/docker-compose.yml up -d --wait
	@echo "→ waiting for the first scrapes…"; sleep 15
	python3 scripts/discover.py --out demo/capability_map.json
	python3 scripts/forge_dashboards.py --capability demo/capability_map.json \
		--blueprints auto --deploy --with-alerts --out-dir demo/generated
	$(MAKE) rules
	@echo; echo "Grafana → $(GRAFANA_URL)  (admin/admin) · dossier « AI Observability »"
	@echo "Recording rules chargées : attendre leur évaluation, puis 'make forge' pour raccourcir les requêtes de coût."

forge: ## Re-générer + re-déployer sur la stack de démo
	python3 scripts/discover.py --out demo/capability_map.json
	python3 scripts/forge_dashboards.py --capability demo/capability_map.json \
		--blueprints auto --deploy --with-alerts --out-dir demo/generated
	$(MAKE) rules

rules: ## Charger les règles générées et signaler un échec de rechargement
	cp -f demo/generated/prometheus_rules_llmops.yml demo/rules/
	curl --fail --show-error --silent -X POST "$(PROMETHEUS_URL)/-/reload"

shots: ## Captures réelles de tous les dashboards déployés
	python3 scripts/visual_audit.py --dashboards demo/generated --out demo/shots

demo-down: ## Tout arrêter et nettoyer
	docker compose -f demo/docker-compose.yml down -v
	python3 -c "import pathlib,shutil; shutil.rmtree('demo/generated',ignore_errors=True); [p.unlink() for p in pathlib.Path('demo').glob('capability_map.json')]; [p.unlink() for p in pathlib.Path('demo/rules').glob('*.yml')]"

package: ## Construire et vérifier le .skill reproductible
	python3 tools/package.py
	python3 tools/package.py --verify

scan: ## Analyse de sécurité du LIVRABLE (NVIDIA SkillSpector)
	python3 tools/package.py
	python3 -c "import zipfile,shutil,pathlib; d=pathlib.Path('/tmp/skillscan'); shutil.rmtree(d, ignore_errors=True); zipfile.ZipFile('dist/grafana-llmops-forge.skill').extractall(d)"
	skillspector scan /tmp/skillscan/grafana-llmops-forge --no-llm

selftest: ## Rendu des 7 blueprints hors ligne
	cd scripts && python3 forge_dashboards.py --selftest --with-alerts

audit: ## 27+ contrôles hors ligne, 4 topologies
	python3 tests/audit_harness.py

test: selftest audit
