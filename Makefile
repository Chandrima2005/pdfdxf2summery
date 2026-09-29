.PHONY: install data test eval eval-llm app desktop docker

install:
	pip install -r requirements-dev.txt

data:
	python -m cad_copilot.samples --out data/samples
	python -m cad_copilot.eval.generate_questions

test:
	pytest -q

eval:
	python -m cad_copilot.eval.run_eval --provider heuristic

eval-llm:
	python -m cad_copilot.eval.run_eval --provider $${LLM_PROVIDER:-openai} --raw-baseline

app:
	uvicorn app.server:app --port 8501 --reload

desktop:
	python app/run_desktop.py

docker:
	docker build -t cad-copilot . && docker run -p 7860:7860 --env-file .env cad-copilot
