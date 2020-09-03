test: lint
	python -m pytest --cov-report=html --cov-report=term --cov=jenkins_exporter tests -v
fmt:
	python -m black jenkins_exporter tests
lint:
	python -m black --check jenkins_exporter tests
