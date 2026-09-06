# =============================================================================
# Milsurp Monitor
#
# Run `make` with no arguments for the list of targets.
# =============================================================================

SHELL       := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PYTHON      ?= python3
VENV        := .venv
VENV_PY     := $(VENV)/bin/python
VENV_PIP    := $(VENV)/bin/pip
PID_FILE    := .server.pid
PORT_FILE   := .milsurp-dev-port
LOG_FILE    := server.log
SHOTS_DIR   := images

# Dev mode: the config file is looked for in the repo root first, the database
# lives in the repo root, and the port is chosen dynamically.
export MILSURP_ENV := dev

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Help — `make` with no target prints this.
#
# Targets are documented with a `## description` comment on the target line and
# grouped by `##@ Section` headers, so the list below can never drift out of
# sync with the targets that actually exist.
# -----------------------------------------------------------------------------
.PHONY: help
help:
	@printf '\n  \033[1;97mMilsurp Monitor\033[0m — military surplus listing tracker\n'
	@printf '  \033[2mUsage: make <target>\033[0m\n'
	@awk 'BEGIN {FS = ":.*##"} \
		/^##@/ { printf "\n  \033[1;94m%s\033[0m\n", substr($$0, 5); next } \
		/^[a-zA-Z0-9_-]+:.*?##/ { printf "    \033[96m%-18s\033[0m %s\n", $$1, $$2 } \
	' $(MAKEFILE_LIST)
	@printf '\n  \033[2mFirst time? Run: make install-dev && make init && make start\033[0m\n\n'

##@ Setup

.PHONY: install-dev
install-dev: ## Create .venv, install every dev dependency, scanner and system package
	@scripts/install-dev.sh

$(VENV_PY):
	@echo "No virtualenv found — run 'make install-dev' first." >&2
	@exit 1

.PHONY: install
install: $(VENV_PY) frontend/node_modules ## Install app dependencies only (no system packages)
	@$(VENV_PIP) install --quiet -r backend/requirements.txt
	@echo "Dependencies installed."

frontend/node_modules: frontend/package.json
	@cd frontend && npm install --no-audit --no-fund
	@touch frontend/node_modules

.PHONY: secrets
secrets: $(VENV_PY) ## Generate security secrets to paste into config.yaml
	@$(VENV_PY) backend/cli.py secrets

.PHONY: config
config: ## Copy config.yaml.sample to config.yaml (dev), if absent
	@if [ -f config.yaml ]; then \
		echo "config.yaml already exists — leaving it alone."; \
	else \
		cp config.yaml.sample config.yaml; \
		chmod 600 config.yaml; \
		echo "Created config.yaml (mode 600, gitignored)."; \
		echo "Edit it — at minimum set security.* and admin.password."; \
		echo "Run 'make secrets' for real secret values."; \
	fi

##@ Database

.PHONY: migrate
migrate: $(VENV_PY) ## Create or upgrade the database to the newest schema
	@$(VENV_PY) scripts/dbupdate.py

.PHONY: migrate-status
migrate-status: $(VENV_PY) ## Show the current and pending schema revisions
	@$(VENV_PY) scripts/dbupdate.py --status

.PHONY: migration
migration: $(VENV_PY) ## Create a new migration: make migration m="add widget"
	@if [ -z "$(m)" ]; then echo 'Usage: make migration m="what changed"' >&2; exit 1; fi
	@$(VENV)/bin/alembic -c backend/alembic.ini revision --autogenerate -m "$(m)"

.PHONY: init
init: migrate ## Set up the database, seed the site list and the admin account
	@$(VENV_PY) backend/cli.py init

.PHONY: passwd
passwd: $(VENV_PY) ## Set a user's password: make passwd user=admin
	@$(VENV_PY) backend/cli.py passwd "$(or $(user),admin)"

##@ Run

.PHONY: start
start: install migrate frontend/dist/index.html ## Rebuild the UI and (re)start the app
	@# Always stop first, so `make start` is a restart rather than a no-op when
	@# something is already running. The frontend is rebuilt by the
	@# frontend/dist/index.html prerequisite above whenever its sources change.
	@# The URL is only printed once /api/health answers: run.py writes the port
	@# file before uvicorn binds, so the file alone is not a readiness signal.
	@$(MAKE) --no-print-directory stop
	@rm -f $(PORT_FILE)
	@nohup $(VENV_PY) backend/run.py > $(LOG_FILE) 2>&1 & \
		echo $$! > $(PID_FILE)
	@for i in $$(seq 1 60); do [ -s $(PORT_FILE) ] && break; sleep 0.25; done; \
		PORT=$$(cat $(PORT_FILE) 2>/dev/null || echo '?'); \
		if [ "$$PORT" = '?' ]; then \
			printf '\n  \033[1;91m✗ The app did not start. Last lines of %s:\033[0m\n\n' "$(LOG_FILE)"; \
			tail -20 $(LOG_FILE); \
			exit 1; \
		fi; \
		for i in $$(seq 1 80); do \
			curl -sf "http://127.0.0.1:$$PORT/api/health" >/dev/null 2>&1 && break; \
			sleep 0.25; \
		done; \
		if ! curl -sf "http://127.0.0.1:$$PORT/api/health" >/dev/null 2>&1; then \
			printf '\n  \033[1;91m✗ Port %s was chosen but the app is not answering. Last lines of %s:\033[0m\n\n' "$$PORT" "$(LOG_FILE)"; \
			tail -20 $(LOG_FILE); \
			exit 1; \
		fi; \
		printf '\n  \033[1;92m▲ Milsurp Monitor is running\033[0m\n'; \
		printf '    \033[1;96mhttp://localhost:%s\033[0m\n' "$$PORT"; \
		printf '    \033[2mPID %s · logs: %s · stop: make stop\033[0m\n\n' "$$(cat $(PID_FILE))" "$(LOG_FILE)"

.PHONY: stop
stop: ## Stop the app
	@# Say what is about to be interrupted. A Royal Tiger scan is a quarter of
	@# an hour of a vendor's bandwidth, and `make start` stops first, so
	@# restarting the app used to kill one silently. Only asks on a terminal;
	@# set FORCE=1 to skip the prompt in a script.
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		if ! $(VENV_PY) backend/cli.py running-scans --quiet 2>/dev/null; then \
			printf '\n  \033[1;93m! A scan is in flight:\033[0m\n'; \
			$(VENV_PY) backend/cli.py running-scans --quiet 2>/dev/null || true; \
			printf '    \033[2mWhatever it has already reconciled is saved; the rest is re-scraped\n'; \
			printf '    next run. Wait for it to finish to avoid re-fetching the remainder.\033[0m\n\n'; \
			if [ -t 0 ] && [ -z "$(FORCE)" ]; then \
				printf '  Stop anyway? [y/N] '; read -r reply; \
				case "$$reply" in [yY]*) ;; *) echo "  Left running."; exit 1;; esac; \
			fi; \
		fi; \
	fi
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		PID=$$(cat $(PID_FILE)); \
		kill "$$PID" 2>/dev/null || true; \
		for i in $$(seq 1 40); do kill -0 "$$PID" 2>/dev/null || break; sleep 0.25; done; \
		if kill -0 "$$PID" 2>/dev/null; then \
			kill -9 "$$PID" 2>/dev/null || true; \
			echo "Stopped (PID $$PID, forced)."; \
		else \
			echo "Stopped (PID $$PID)."; \
		fi; \
	elif [ -f $(PID_FILE) ]; then \
		echo "Not running (stale PID file removed)."; \
	fi; \
	rm -f $(PID_FILE) $(PORT_FILE)

.PHONY: restart
restart: start ## Restart the app (an alias for start, which now stops first)

.PHONY: status
status: ## Report whether the app is running, and on which port
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		echo "Running (PID $$(cat $(PID_FILE))) at http://localhost:$$(cat $(PORT_FILE) 2>/dev/null)"; \
	else \
		echo "Not running."; \
	fi

.PHONY: logs
logs: ## Follow the application log
	@tail -f $(LOG_FILE)

.PHONY: dev
dev: ## Run the backend and the Vite dev server with hot reload (foreground)
	@scripts/dev.sh

frontend/dist/index.html: frontend/node_modules $(shell find frontend/src frontend/public -type f 2>/dev/null)
	@cd frontend && npm run build

.PHONY: build-frontend
build-frontend: frontend/node_modules ## Build the production UI bundle
	@cd frontend && npm run build

##@ Scraping

.PHONY: photos
photos: $(VENV_PY) ## Download queued photos without re-scraping (make photos limit=2000)
	@if [ -n "$(limit)" ]; then \
		$(VENV_PY) backend/cli.py fetch-photos --limit "$(limit)"; \
	else \
		$(VENV_PY) backend/cli.py fetch-photos; \
	fi

.PHONY: reclassify
reclassify: $(VENV_PY) ## Re-derive rifle/handgun for stored listings (no network)
	@$(VENV_PY) backend/cli.py reclassify

.PHONY: scan
scan: $(VENV_PY) ## Scan every enabled site now (or one: make scan site=empire-arms)
	@if [ -n "$(site)" ]; then \
		$(VENV_PY) backend/cli.py scan --site "$(site)"; \
	else \
		$(VENV_PY) backend/cli.py scan; \
	fi

.PHONY: sites
sites: $(VENV_PY) ## List sites, their schedules and last scan
	@$(VENV_PY) backend/cli.py sites

.PHONY: digest
digest: $(VENV_PY) ## Send any email digests that are due
	@$(VENV_PY) backend/cli.py digest

##@ Quality

.PHONY: lint
lint: ## Format with black, then run every linter (fails on any finding)
	@scripts/lint.sh

.PHONY: lint-fix
lint-fix: ## Auto-fix what the linters can fix, then re-check
	@scripts/lint.sh --fix

.PHONY: test
test: test-backend test-frontend ## Run backend + frontend tests with coverage gates

.PHONY: test-backend
test-backend: $(VENV_PY) ## Run the pytest suite (fails under 65% coverage)
	@scripts/test-backend.sh

.PHONY: test-frontend
test-frontend: frontend/node_modules ## Run the Playwright suite (fails under 65% coverage)
	@scripts/test-frontend.sh

.PHONY: coverage
coverage: ## Regenerate the README coverage badges from the last test run
	@$(VENV_PY) scripts/coverage_badges.py

.PHONY: security
security: ## Run the same security scanners CI runs, locally
	@scripts/security.sh

.PHONY: install-hooks
install-hooks: ## Install the git pre-commit / pre-push hooks
	@scripts/install-hooks.sh

##@ Release

.PHONY: release
release: ## Bump the version, tag it and push (make release VERSION=1.2.3.4)
	@scripts/release.sh

##@ Documentation

.PHONY: screenshots
screenshots: ## Capture README screenshots into images/ with Playwright
	@scripts/screenshots.sh

##@ Housekeeping

.PHONY: clean
clean: stop ## Remove build output, caches and virtualenvs
	@rm -rf frontend/dist frontend/node_modules frontend/.nyc_output frontend/coverage
	@rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov coverage.xml
	@rm -f $(LOG_FILE) $(PID_FILE) $(PORT_FILE)
	@find . -type d -name __pycache__ -not -path './.git/*' -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned build artifacts. The database and image store were left alone."

.PHONY: clean-data
clean-data: ## DESTRUCTIVE — delete the dev database and downloaded photos
	@printf 'This deletes milsurp.db and every downloaded photo. Type YES to confirm: '; \
	read -r reply; \
	if [ "$$reply" = "YES" ]; then \
		rm -f milsurp.db milsurp.db-wal milsurp.db-shm; \
		rm -rf data/images; \
		echo "Deleted."; \
	else \
		echo "Aborted."; \
	fi
