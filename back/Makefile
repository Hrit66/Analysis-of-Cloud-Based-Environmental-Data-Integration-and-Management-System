.PHONY: help install dev test lint format docker-build docker-up docker-down docker-logs clean

help:
	@echo "Available commands:"
	@echo "  install      - Install dependencies"
	@echo "  dev          - Run development server with hot reload"
	@echo "  test         - Run tests"
	@echo "  lint         - Run linting (ruff)"
	@echo "  format       - Format code (ruff format)"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-up    - Start Docker Compose services"
	@echo "  docker-down  - Stop Docker Compose services"
	@echo "  docker-logs  - View Docker Compose logs"
	@echo "  clean        - Clean up build artifacts"

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v

lint:
	ruff check app/ tests/

format:
	ruff format app/ tests/

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

clean:
	rm -rf __pycache__ .pytest_cache .coverage htmlcov .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true