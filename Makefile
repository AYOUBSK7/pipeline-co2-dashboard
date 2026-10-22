# Raccourcis (Linux / macOS / Git Bash). Sous Windows sans make,
# copiez simplement la commande qui suit chaque cible.

.PHONY: install base etl test dashboard tout

install:        ## installer les dépendances Python
	pip install -r requirements.txt

base:           ## démarrer PostgreSQL avec Docker
	docker compose up -d

etl:            ## exécuter le pipeline complet
	python -m etl.pipeline

test:           ## lancer les tests unitaires
	pytest -v

dashboard:      ## ouvrir le tableau de bord
	streamlit run dashboard/app.py

tout: base etl dashboard
