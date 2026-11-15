#!/bin/zsh
# Native application/model host only. Candidate Python runs exclusively in Kata.
set -eu
repo="${0:A:h:h:h}"
cd "$repo"
[[ "$(uname -sm)" == 'Darwin arm64' ]] || { print -u2 'Requires native macOS ARM64'; exit 1; }
py="${KATAAI_PYTHON:-$repo/.venv/bin/python}"
"$py" -c 'import sys,platform; assert sys.version_info[:2] == (3,12) and platform.machine() == "arm64"'
export PYTHONPATH="$repo/backend:$repo${PYTHONPATH:+:$PYTHONPATH}"
mode="${1:-}"
[[ $# -gt 0 ]] && shift
case "$mode" in
  api)
    export KATAAI_API_PORT="${KATAAI_API_PORT:-8000}"
    exec "$py" -m uvicorn app.main:app --host 127.0.0.1 --port "$KATAAI_API_PORT" "$@"
    ;;
  worker)
    : "${KATAAI_KUBECONFIG:?Set the approved application kubeconfig path}"
    : "${KATAAI_KUBE_CONTEXT:?Set the approved application context}"
    : "${KATAAI_JOURNAL:?Set the persistent journal path in a private directory}"
    exec "$py" -m app.kata_demo_worker --kubeconfig "$KATAAI_KUBECONFIG" \
      --context "$KATAAI_KUBE_CONTEXT" --journal "$KATAAI_JOURNAL" "$@"
    ;;
  model)
    : "${KATAAI_MODEL_PATH:?Set the existing Qwen3.5-9B-Q4_K_M GGUF path}"
    exec llama-server --model "$KATAAI_MODEL_PATH" --device MTL0 --gpu-layers 99 \
      --host 127.0.0.1 --port 8080 --ctx-size 4096 --parallel 1 --jinja "$@"
    ;;
  *) print -u2 'Usage: backend/scripts/run_mvp.zsh api | model | worker (--once|--loop)'; exit 2 ;;
esac
