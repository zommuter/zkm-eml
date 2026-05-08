# Usage:
#   make install-hook              (default mail repo: ~/mail)
#   make install-hook MAIL=~/work-mail
#   make uninstall-hook
MAIL ?= $(HOME)/mail
HOOK_SRC := $(abspath hooks/post-commit)
HOOK_DST := $(MAIL)/.git/hooks/post-commit

.PHONY: install-hook uninstall-hook

install-hook:
	@test -d "$(MAIL)/.git" || { echo "Not a git repo: $(MAIL)" >&2; exit 1; }
	@ln -sfn "$(HOOK_SRC)" "$(HOOK_DST)"
	@echo "Symlinked: $(HOOK_DST) -> $(HOOK_SRC)"

uninstall-hook:
	@if [ -L "$(HOOK_DST)" ]; then \
		rm "$(HOOK_DST)"; echo "Removed: $(HOOK_DST)"; \
	else echo "No symlink at $(HOOK_DST)"; fi
