SHELL := /bin/bash
GRAFANA_URL ?= http://localhost:3000
export GRAFANA_URL
export GRAFANA_USER ?= admin
export GRAFANA_PASSWORD ?= admin

.PHONY: demo demo-down test selftest forge audit

demo: ## Stack complète : Grafana + Prometheus + métriques LLM synthétiques, puis forge
	docker compose -f demo/docker-compose.yml up -d
	@echo "→ attente de Grafana…"; \
	for i in $$(seq 1 60); do curl -sf $(GRAFANA_URL)/api/health >/dev/null && break; sleep 2; done
	@echo "→ attente des premières métriques…"; sleep 20
	python3 scripts/discover.py --out demo/capability_map.json
	python3 scripts/forge_dashboards.py --capability demo/capability_map.json \
		--blueprints auto --deploy --with-alerts --out-dir demo/generated
	@cp -f demo/generated/prometheus_rules_llmops.yml demo/rules/ 2>/dev/null || true
	@curl -sX POST http://localhost:9090/-/reload >/dev/null 2>&1 || true
	@echo; echo "Grafana → $(GRAFANA_URL)  (admin/admin) · dossier « AI Observability »"
	@echo "Les recording rules de coût sont chargées : relancer 'make forge' pour passer les panels en O(1)."

forge: ## Re-générer + re-déployer sur la stack de démo
	python3 scripts/discover.py --out demo/capability_map.json
	python3 scripts/forge_dashboards.py --capability demo/capability_map.json \
		--blueprints auto --deploy --with-alerts --out-dir demo/generated

shots: ## Captures réelles de tous les dashboards déployés
	python3 scripts/visual_audit.py --dashboards demo/generated --out demo/shots

demo-down: ## Tout arrêter et nettoyer
	docker compose -f demo/docker-compose.yml down -v
	python3 -c "import pathlib,shutil; shutil.rmtree('demo/generated',ignore_errors=True); [p.unlink() for p in pathlib.Path('demo').glob('capability_map.json')]; [p.unlink() for p in pathlib.Path('demo/rules').glob('*.yml')]"

package: ## Construire le .skill (nettoie le bytecode avant copie)
	python3 -c "import pathlib,shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]; [p.unlink() for p in pathlib.Path('.').rglob('*.pyc')]" 
	@echo "arbre nettoyé — packager depuis skill-creator"

scan: ## Analyse de sécurité du LIVRABLE (NVIDIA SkillSpector)
	python3 tools/package.py
	python3 -c "import zipfile,shutil,pathlib; d=pathlib.Path('/tmp/skillscan'); shutil.rmtree(d, ignore_errors=True); zipfile.ZipFile('dist/grafana-llmops-forge.skill').extractall(d)"
	skillspector scan /tmp/skillscan/grafana-llmops-forge --no-llm

selftest: ## Rendu des 7 blueprints hors ligne
	cd scripts && python3 forge_dashboards.py --selftest --with-alerts

audit: ## 27+ contrôles hors ligne, 4 topologies
	python3 tests/audit_harness.py

test: selftest audit
