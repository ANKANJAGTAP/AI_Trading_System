.PHONY: up down build logs migrate verify fmt ps

up:        ## start the full stack
	docker compose up -d --build

down:      ## stop the stack
	docker compose down

build:     ## build images
	docker compose build

logs:      ## tail logs
	docker compose logs -f

ps:        ## list services
	docker compose ps

migrate:   ## run DB migrations inside a container
	docker compose run --rm api migrate

verify:    ## run the Phase 0 acceptance check (needs .env with Kite creds)
	docker compose run --rm engine python scripts/verify_phase0.py

fmt:       ## format + lint
	ruff check --fix . && black .
