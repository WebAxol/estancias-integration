# Monitoring Setup Summary

## What Was Configured

This document summarizes the Prometheus and Grafana monitoring setup for the Estancias API.

## Files Created/Modified

### New Configuration Files

1. **prometheus.yml**
   - Prometheus scraping configuration
   - Scrapes API metrics every 10 seconds from `/metrics` endpoint
   - Includes self-monitoring for Prometheus

2. **grafana/provisioning/datasources/prometheus.yml**
   - Auto-configures Prometheus as Grafana datasource
   - No manual setup needed in Grafana UI

3. **grafana/provisioning/dashboards/dashboard.yml**
   - Dashboard provisioning configuration
   - Points to dashboard definitions directory

4. **grafana/provisioning/dashboards/definitions/api-dashboard.json**
   - Pre-built dashboard with 9 panels:
     * Request rate, P95 latency, error rate stats
     * Request rate by endpoint (time series)
     * Response time percentiles (P50/P95/P99)
     * HTTP status codes distribution
     * Error rate by type and endpoint
     * Top 10 endpoints table

5. **MONITORING.md**
   - Comprehensive documentation
   - Architecture diagram
   - Metrics descriptions
   - PromQL query examples
   - Troubleshooting guide

6. **start-monitoring.sh**
   - Helper script to start the entire stack
   - Validates environment configuration
   - Waits for all services to be healthy
   - Shows access URLs

7. **test-metrics.sh**
   - Validation script for the monitoring setup
   - Checks all endpoints
   - Generates sample traffic
   - Verifies Prometheus is scraping metrics

### Modified Files

8. **docker-compose.yml**
   - Added `prometheus` service (port 9090, localhost only)
   - Added `grafana` service (port 3000, all interfaces)
   - Added volume mounts for configurations
   - Added health checks for new services
   - Set `METRICS_ENABLED=true` for API

9. **.env.sample**
   - Added Prometheus and Grafana configuration variables:
     * `PROMETHEUS_PORT=9090`
     * `GRAFANA_PORT=3000`
     * `GRAFANA_ADMIN_USER=admin`
     * `GRAFANA_ADMIN_PASSWORD=admin`

10. **README.md**
    - Updated with monitoring information
    - Added quick start instructions
    - Added links to MONITORING.md

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Docker Compose Network                     │
│                                                                │
│  ┌─────────────┐         ┌──────────────┐                    │
│  │ PostgreSQL  │◄────────│  API (8000)  │                    │
│  │   (5432)    │         │              │                    │
│  └─────────────┘         │  /metrics    │                    │
│                          └───────┬──────┘                    │
│                                  │                            │
│                                  │ scrapes every 10s          │
│                                  │                            │
│                          ┌───────▼──────┐                    │
│                          │  Prometheus  │                    │
│                          │    (9090)    │                    │
│                          └───────┬──────┘                    │
│                                  │                            │
│                                  │ queries                    │
│                                  │                            │
│                          ┌───────▼──────┐                    │
│                          │   Grafana    │                    │
│                          │    (3000)    │                    │
│                          └──────────────┘                    │
└──────────────────────────────────────────────────────────────┘
```

## Metrics Collected

### 1. http_requests_total (Counter)
- Total HTTP requests
- Labels: method, endpoint, status_code

### 2. http_request_duration_seconds (Histogram)
- Request duration distribution
- Labels: method, endpoint, status_code
- Buckets: 5ms to 10s

### 3. http_errors_total (Counter)
- Total HTTP errors (status >= 400)
- Labels: method, endpoint, status_code, error_type

## Quick Start

```bash
cd integration

# Start everything
./start-monitoring.sh

# Test the setup
./test-metrics.sh

# Or manually
docker-compose up -d
```

## Access URLs

| Service | URL | Bound To |
|---------|-----|----------|
| API Docs | http://localhost:8000/docs | 0.0.0.0 (all interfaces) |
| API Metrics | http://localhost:8000/metrics | 0.0.0.0 |
| Prometheus | http://localhost:9090 | 127.0.0.1 (localhost only) |
| Grafana | http://localhost:3000 | 0.0.0.0 |
| Database | localhost:5432 | 127.0.0.1 |

## Default Credentials

- **Grafana**: admin / admin (change in `.env`)

## Service Dependencies

```
db (healthy)
  ↓
api (healthy)
  ↓
prometheus (healthy)
  ↓
grafana (healthy)
```

## Data Persistence

Three Docker volumes store persistent data:

- `db_data`: PostgreSQL database
- `prometheus_data`: Prometheus time-series data (metrics history)
- `grafana_data`: Grafana dashboards, users, settings

## Environment Variables

Add to `.env`:

```bash
# Monitoring
PROMETHEUS_PORT=9090
GRAFANA_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
```

## Testing

Generate traffic and check metrics:

```bash
# Generate some requests
for i in {1..100}; do curl -s http://localhost:8000/docs > /dev/null; done

# Check raw metrics
curl http://localhost:8000/metrics

# Query Prometheus
curl 'http://localhost:9090/api/v1/query?query=http_requests_total'

# View in Grafana
# Open http://localhost:3000 and go to "Estancias API Monitoring" dashboard
```

## Next Steps

### For API Monitoring
- ✅ Prometheus scraping
- ✅ Grafana dashboards
- ✅ HTTP metrics
- ⏳ Database metrics (next phase)
- ⏳ Alerting rules
- ⏳ Alert notifications

### For Database Monitoring
See the database monitoring guide (to be created) for:
- PostgreSQL exporter setup
- Database-specific dashboards
- Query performance metrics
- Connection pool monitoring

## Troubleshooting

### Services won't start
```bash
docker-compose logs prometheus
docker-compose logs grafana
docker-compose logs api
```

### Metrics not showing
1. Check API metrics endpoint: `curl http://localhost:8000/metrics`
2. Check Prometheus targets: http://localhost:9090/targets
3. Generate traffic: `curl http://localhost:8000/docs`
4. Wait 10-15 seconds for scrape

### Grafana shows "No Data"
1. Check time range (last 1 hour)
2. Verify Prometheus datasource in Grafana
3. Check if Prometheus has data: http://localhost:9090/graph
4. Generate more traffic to the API

## Documentation

- **MONITORING.md**: Complete monitoring guide with PromQL queries
- **README.md**: General integration documentation
- **This file**: Setup summary

## Implementation Notes

The API already had `prometheus-client` installed and metrics implementation in:
- `src/infrastructure/metrics/prometheus_metrics.py` - MetricsCollector class
- `src/infrastructure/metrics/metrics_middleware.py` - FastAPI middleware
- `src/infrastructure/routes/metrics.py` - /metrics endpoint

We only needed to:
1. Add Prometheus and Grafana services to docker-compose
2. Create Prometheus scraping configuration
3. Create Grafana provisioning files
4. Create dashboard definitions
5. Update documentation

The metrics are enabled by default via `METRICS_ENABLED=true` environment variable.
