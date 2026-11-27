#!/bin/bash
# Quick start script for the monitoring stack

set -e

echo "🚀 Starting Estancias Monitoring Stack"
echo "======================================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found"
    echo "📝 Copying .env.sample to .env"
    cp .env.sample .env
    echo ""
    echo "⚠️  Please edit .env and fill in the required values:"
    echo "   - POSTGRES_PASSWORD"
    echo "   - JWT_SECRET (at least 32 characters)"
    echo "   - BOOTSTRAP_ADMIN_PASSWORD"
    echo ""
    echo "Then run this script again."
    exit 1
fi

echo "✅ Found .env file"
echo ""

# Check if required variables are set
if ! grep -q "POSTGRES_PASSWORD=.\+" .env; then
    echo "❌ POSTGRES_PASSWORD is not set in .env"
    exit 1
fi

if ! grep -q "JWT_SECRET=.\+" .env; then
    echo "❌ JWT_SECRET is not set in .env"
    exit 1
fi

echo "✅ Required environment variables are set"
echo ""

# Start the services
echo "🐳 Starting Docker Compose services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to become healthy..."
echo ""

# Wait for services
timeout=120
elapsed=0
interval=5

while [ $elapsed -lt $timeout ]; do
    db_healthy=$(docker inspect --format='{{.State.Health.Status}}' estancias-db 2>/dev/null || echo "starting")
    api_healthy=$(docker inspect --format='{{.State.Health.Status}}' estancias-api 2>/dev/null || echo "starting")
    prom_healthy=$(docker inspect --format='{{.State.Health.Status}}' estancias-prometheus 2>/dev/null || echo "starting")
    grafana_healthy=$(docker inspect --format='{{.State.Health.Status}}' estancias-grafana 2>/dev/null || echo "starting")
    
    echo "   DB: $db_healthy | API: $api_healthy | Prometheus: $prom_healthy | Grafana: $grafana_healthy"
    
    if [ "$db_healthy" = "healthy" ] && [ "$api_healthy" = "healthy" ] && [ "$prom_healthy" = "healthy" ] && [ "$grafana_healthy" = "healthy" ]; then
        echo ""
        echo "✅ All services are healthy!"
        break
    fi
    
    sleep $interval
    elapsed=$((elapsed + interval))
done

if [ $elapsed -ge $timeout ]; then
    echo ""
    echo "⚠️  Timeout waiting for services to become healthy"
    echo "Check logs with: docker-compose logs"
    exit 1
fi

echo ""
echo "🎉 Monitoring Stack is ready!"
echo ""
echo "📊 Access the services:"
echo "   • API Documentation:  http://localhost:8000/docs"
echo "   • API Metrics:        http://localhost:8000/metrics"
echo "   • Prometheus:         http://localhost:9090"
echo "   • Grafana:            http://localhost:3000"
echo ""
echo "🔑 Grafana Login:"
echo "   Username: admin"
echo "   Password: admin (or check GRAFANA_ADMIN_PASSWORD in .env)"
echo ""
echo "📈 The 'Estancias API Monitoring' dashboard is pre-configured"
echo ""
echo "💡 Generate some traffic to see metrics:"
echo "   curl http://localhost:8000/docs"
echo ""
echo "📖 For more information, see MONITORING.md"
