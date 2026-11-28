#!/bin/bash
# Script to verify PostgreSQL monitoring setup

set -e

echo "==================================="
echo "PostgreSQL Monitoring Health Check"
echo "==================================="
echo ""

# Check if containers are running
echo "1. Checking container status..."
echo "-----------------------------------"
docker ps --filter "name=estancias-postgres-exporter" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Check postgres-exporter metrics endpoint
echo "2. Testing postgres-exporter metrics endpoint..."
echo "-----------------------------------"
if curl -s http://localhost:9187/metrics > /dev/null; then
    echo "✓ postgres-exporter is responding on port 9187"
    echo ""
    echo "Sample metrics:"
    curl -s http://localhost:9187/metrics | grep -E "^(pg_up|pg_database_size|pg_connection_stats)" | head -10
else
    echo "✗ postgres-exporter is not responding on port 9187"
    echo "Check logs: docker logs estancias-postgres-exporter"
fi
echo ""

# Check Prometheus targets
echo "3. Checking Prometheus targets..."
echo "-----------------------------------"
if curl -s http://localhost:9090/api/v1/targets > /dev/null; then
    echo "✓ Prometheus is responding on port 9090"
    
    # Check if postgresql target is up
    TARGET_STATUS=$(curl -s http://localhost:9090/api/v1/targets | grep -o '"job":"postgresql"[^}]*"health":"[^"]*"' | grep -o '"health":"[^"]*"' | cut -d'"' -f4)
    
    if [ "$TARGET_STATUS" = "up" ]; then
        echo "✓ PostgreSQL target is UP in Prometheus"
    else
        echo "✗ PostgreSQL target status: $TARGET_STATUS"
    fi
else
    echo "✗ Prometheus is not responding on port 9090"
fi
echo ""

# Check if custom queries are working
echo "4. Testing custom PostgreSQL queries..."
echo "-----------------------------------"
CUSTOM_METRICS=$(curl -s http://localhost:9187/metrics | grep -c "^pg_database_size" || echo "0")
if [ "$CUSTOM_METRICS" -gt 0 ]; then
    echo "✓ Custom queries are working ($CUSTOM_METRICS pg_database_size metrics found)"
else
    echo "✗ Custom queries may not be working"
    echo "Check queries.yaml and exporter logs"
fi
echo ""

# Summary
echo "==================================="
echo "Summary"
echo "==================================="
echo ""
echo "Access URLs:"
echo "  - PostgreSQL Exporter: http://localhost:9187/metrics"
echo "  - Prometheus:          http://localhost:9090"
echo "  - Grafana:             http://localhost:3000"
echo ""
echo "To view logs:"
echo "  docker logs estancias-postgres-exporter"
echo "  docker logs estancias-prometheus"
echo ""
echo "To restart services:"
echo "  docker compose restart postgres-exporter prometheus"
echo ""
