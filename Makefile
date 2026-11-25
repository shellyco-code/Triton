.PHONY: install test lint fmt run demo chaos evals docker deploy

install:   ## Install runtime + dev dependencies
	pip install -r requirements-dev.txt

test:      ## Run the test suite (no cluster or API key needed)
	pytest

lint:      ## Lint and check formatting
	ruff check . && ruff format --check .

fmt:       ## Auto-fix lint and format
	ruff check . --fix && ruff format .

run:       ## Run the API with hot reload
	uvicorn app.main:app --reload

demo:      ## Run the dashboard on sample data (no cluster needed)
	DATABASE_URL=sqlite:///./demo.db python -m scripts.seed_demo_data
	DATABASE_URL=sqlite:///./demo.db ENABLE_POLLER=false uvicorn app.main:app

chaos:     ## Deploy broken workloads to the current cluster
	python -m app.chaos.break_stuff all

evals:     ## Score the agent on recorded scenarios (needs GROQ_API_KEY)
	python -m evals.run --trials 3

docker:    ## Build the container image
	docker build -t triton:latest .

deploy:    ## Build into minikube and deploy
	minikube image build -t triton:latest .
	kubectl apply -k deploy/k8s
