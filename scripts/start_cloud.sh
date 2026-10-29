#!/usr/bin/env bash
# ==============================================================================
# PharmaInsight Unified Cloud Runner (Single-Container Free-Tier PaaS Mode)
# ==============================================================================
# Starts both the FastAPI REST backend (internal port 8000) and the Streamlit
# Dashboard on the cloud provider's assigned public $PORT (defaults to 8501).
# Compatible with Render (Free Web Service), Railway, Fly.io, and Heroku.
# ==============================================================================

set -eo pipefail

PUBLIC_PORT="${PORT:-8501}"
INTERNAL_API_PORT="${INTERNAL_API_PORT:-8000}"

echo "=============================================================================="
echo "🚀 PharmaInsight Platform: Booting Cloud Unified Container"
echo "   Public Port:       ${PUBLIC_PORT}"
echo "   Internal API Port: ${INTERNAL_API_PORT}"
echo "   LLM Provider:      ${LLM_PROVIDER:-mock}"
echo "=============================================================================="

# Graceful cleanup on termination signal
cleanup() {
    echo "🛑 Caught signal, shutting down all services..."
    kill $(jobs -p) 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 1. Start FastAPI REST Service in background
echo "⚡ Starting FastAPI backend service on 127.0.0.1:${INTERNAL_API_PORT}..."
uvicorn src.api.main:app \
    --host 127.0.0.1 \
    --port "${INTERNAL_API_PORT}" \
    --workers 1 &
API_PID=$!

# 2. Wait for FastAPI healthcheck to pass
echo "⏳ Waiting for API healthcheck to report healthy..."
for i in {1..30}; do
    if curl -s -f "http://127.0.0.1:${INTERNAL_API_PORT}/health" >/dev/null 2>&1; then
        echo "✅ API is up, seed data verified."
        break
    fi
    sleep 0.5
done

# 3. Configure API_URL for dashboard
export API_URL="http://127.0.0.1:${INTERNAL_API_PORT}"

# 4. Start Streamlit Visual Analytics Dashboard in foreground
echo "🎨 Starting Streamlit Visual Dashboard on 0.0.0.0:${PUBLIC_PORT}..."
exec streamlit run src/dashboard/app.py \
    --server.port="${PUBLIC_PORT}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.serverAddress="localhost"
