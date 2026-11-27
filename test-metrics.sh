#!/bin/bash
# Script to test the metrics endpoint and generate sample data

set -e

API_URL="${API_URL:-http://localhost:8000}"

echo "🧪 Testing Estancias API Metrics"
echo "================================"
echo ""

# Check if API is running
echo "1️⃣  Checking API availability..."
if curl -f -s "${API_URL}/docs" > /dev/null; then
    echo "   ✅ API is running"
else
    echo "   ❌ API is not accessible at ${API_URL}"
    echo "   Make sure the services are running: docker-compose up -d"
    exit 1
fi

echo ""
echo "2️⃣  Checking metrics endpoint..."
metrics_response=$(curl -s "${API_URL}/metrics")
if echo "$metrics_response" | grep -q "http_requests_total"; then
    echo "   ✅ Metrics endpoint is working"
else
    echo "   ❌ Metrics endpoint is not returning expected data"
    echo "   Response: $metrics_response"
    exit 1
fi

echo ""
echo "3️⃣  Current metrics snapshot:"
echo "$metrics_response" | grep -E "^(http_requests_total|http_request_duration_seconds|http_errors_total)" | head -10
echo "   ... (truncated, see full output at ${API_URL}/metrics)"

echo ""
echo "4️⃣  Generating sample traffic..."
# Generate some requests
for i in {1..10}; do
    curl -s "${API_URL}/docs" > /dev/null
    echo -n "."
done
echo ""
echo "   ✅ Generated 10 requests"

echo ""
echo "5️⃣  Checking Prometheus scraping..."
PROM_URL="${PROM_URL:-http://localhost:9090}"
if curl -f -s "${PROM_URL}/-/healthy" > /dev/null; then
    echo "   ✅ Prometheus is healthy"
    
    # Check if metrics are in Prometheus
    sleep 2  # Wait for scrape
    prom_query=$(curl -s "${PROM_URL}/api/v1/query?query=http_requests_total" | grep -o '"status":"success"' || echo "")
    if [ -n "$prom_query" ]; then
        echo "   ✅ Prometheus is collecting metrics"
    else
        echo "   ⚠️  Metrics not yet in Prometheus (may need more time)"
    fi
else
    echo "   ⚠️  Prometheus is not accessible at ${PROM_URL}"
fi

echo ""
echo "6️⃣  Checking Grafana..."
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
if curl -f -s "${GRAFANA_URL}/api/health" > /dev/null; then
    echo "   ✅ Grafana is healthy"
else
    echo "   ⚠️  Grafana is not accessible at ${GRAFANA_URL}"
fi

echo ""
echo "✅ Metrics setup verification complete!"
echo ""
echo "🔗 Quick Links:"
echo "   • Metrics:    ${API_URL}/metrics"
echo "   • Prometheus: ${PROM_URL}"
echo "   • Grafana:    ${GRAFANA_URL}"
echo ""
echo "💡 To see real metrics in Grafana:"
echo "   1. Open ${GRAFANA_URL} (login: admin/admin)"
echo "   2. Go to Dashboards → Estancias API Monitoring"
echo "   3. Generate more traffic with:"
echo "      ab -n 100 -c 5 ${API_URL}/docs"
