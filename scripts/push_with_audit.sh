#!/bin/zsh

# Compatibility entrypoint for older jobs. The single-agent publisher owns
# validation, locking, commit ordering, retries, and failure reporting.
exec "$(cd "$(dirname "$0")" && pwd)/publish_dashboard.sh" "$@"
