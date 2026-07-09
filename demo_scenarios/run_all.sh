#!/usr/bin/env bash
# Run every demo scenario through the real razi harness and collect artifacts.
#
# Usage (from anywhere):
#   ./demo_scenarios/run_all.sh                                  # OpenAI (needs OPENAI_API_KEY)
#   ./demo_scenarios/run_all.sh --test-mode --test-model llama3.1  # local Ollama, no API key
set -uo pipefail
cd "$(dirname "$0")/.."   # repo root

if [[ "$*" != *"--test-mode"* && -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set. Export it, or pass --test-mode to use local Ollama."
  exit 1
fi

SCENARIOS=(
  legal_memo clinical_triage credit_decision claim_adjudication
  resume_screen benefits_eligibility moderation zendesk_troubleshoot
  clinical_triage_redteam_leak clinical_triage_redteam_fake clinical_triage_redteam_lowconf
)

for s in "${SCENARIOS[@]}"; do
  base="${s%%_redteam_*}"
  input="demo_scenarios/inputs/${base//_/-}.json"
  echo ""
  echo "==== razi run ${s}"
  razi run "demo_scenarios/specs/${s}.aispec" --input "$input" "$@" \
    || echo "(non-compliant final result — for red-team specs, the harness refusing IS the demo)"
done

echo ""
echo "==== replaying every recorded run"
for d in runs/*/; do
  [ -d "$d" ] || continue
  rid="$(basename "$d")"
  razi replay "$rid" || true
done

echo ""
echo "==== safety check: scanning artifacts for key material"
if grep -rIl "sk-" runs/ 2>/dev/null | grep -q .; then
  echo "WARNING: possible API key material found in runs/ — inspect before pushing:"
  grep -rIl "sk-" runs/
else
  echo "clean — no key material found in runs/"
fi

echo ""
echo "Publish with:"
echo "  git add demo_scenarios runs"
echo "  git commit -m 'Add demo scenarios with recorded, replayable runs'"
echo "  git push"
