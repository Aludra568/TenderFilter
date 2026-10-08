.PHONY: up down logs test eval dev-backend dev-frontend demo-zip

up:            ## Поднять всё: БД, Redis, API, воркер, фронтенд, LLM
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f backend worker

test:          ## Автотесты бэкенда (SQLite, без внешних сервисов)
	cd backend && python -m pytest -q

eval:          ## Точность на эталонном наборе → backend/eval/report.json
	cd backend && python -m app.evaluation

dev-backend:   ## Бэкенд без Docker: SQLite, очередь в процессе
	cd backend && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm install && npm run dev

demo-zip:      ## Пакет демо-извещений со свежими датами
	curl -o demo_notices.zip http://localhost:8080/api/demo/batch.zip
