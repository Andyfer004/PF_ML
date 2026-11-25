#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:-http://165.22.137.8:8000}"
PREDICTION_MODE="${PREDICTION_MODE:-historica}"
[[ "$PREDICTION_MODE" == vigente || "$PREDICTION_MODE" == historica ]]
TEST_OUTPUT_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_OUTPUT_DIR"' EXIT
curl --fail --silent --show-error "$BASE_URL/health"
curl --fail --silent --show-error "$BASE_URL/precios/actual"
curl --fail --silent --show-error "$BASE_URL/modelo/metricas"
curl --fail --silent --show-error "$BASE_URL/prediccion/historica/semanas?fuente=mem"
for fuel in super regular diesel; do
  curl --fail --silent --show-error "$BASE_URL/precios?combustible=$fuel&limit=2"
  prediction_path="/prediccion?combustible=$fuel&fuente=mem"
  if [[ "$PREDICTION_MODE" == vigente ]]; then
    prediction_path="$prediction_path&modo=vigente"
  fi
  status="$(curl --silent --show-error --output "$TEST_OUTPUT_DIR/$fuel.json" --write-out '%{http_code}' "$BASE_URL$prediction_path")"
  if [[ "$status" != 200 ]] && ! [[ "$PREDICTION_MODE" == vigente && "$status" == 503 && "${ALLOW_STALE_PREDICTION:-0}" == 1 ]]; then
    cat "$TEST_OUTPUT_DIR/$fuel.json" >&2
    echo "Respuesta inesperada en predicción: $status" >&2
    exit 1
  fi
  cat "$TEST_OUTPUT_DIR/$fuel.json"
 done
status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$BASE_URL/precios?combustible=invalido")"
[[ "$status" == 422 ]]
