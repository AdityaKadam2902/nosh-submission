PY ?= python
# SAMPLE=5000 make build  -> fast demo build

.PHONY: setup data inspect build audit embed test eval cli ui clean-db

setup:
	$(PY) -m pip install -r requirements.txt

data:
	$(PY) -m scripts.download_data

inspect:
	$(PY) -m scripts.build_db --inspect

build:
	$(PY) -m scripts.build_db $(if $(SAMPLE),--sample $(SAMPLE))
	$(PY) -m scripts.audit

audit:
	$(PY) -m scripts.audit

embed:
	$(PY) -m pip install -r requirements-embed.txt
	$(PY) -m scripts.build_embeddings

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m eval.run_eval

cli:
	$(PY) -m recipebot.cli

ui:
	streamlit run app.py

clean-db:
	rm -f data/recipes.db
