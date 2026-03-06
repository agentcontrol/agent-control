SHELL := /bin/bash

PNPM ?= pnpm

.PHONY: help install install-no-frozen FORCE

help:
	@echo "UI Makefile targets"
	@echo "  make install                 - install dependencies (frozen lockfile)"
	@echo "  make install-no-frozen       - install dependencies without frozen lockfile"
	@echo "  make <script>                - proxy to pnpm run <script>"
	@echo ""
	@echo "Script name mapping:"
	@echo "  - Use script name directly when it has no ':' (e.g., make dev, make typecheck)"
	@echo "  - Use '--' in place of ':' for pnpm scripts with colons"
	@echo "    examples:"
	@echo "      make lint--fix                 -> pnpm run lint:fix"
	@echo "      make test--integration--ui     -> pnpm run test:integration:ui"
	@echo ""
	@echo "pnpm scripts:"
	@$(PNPM) run help

install:
	$(PNPM) install --frozen-lockfile

install-no-frozen:
	$(PNPM) install

FORCE:
	@:

Makefile makefile GNUmakefile:
	@:

%: FORCE
	$(PNPM) run $(subst --,:,$@)
