# Monitoring Setup

This document describes the monitoring infrastructure for the Estancias API using Prometheus and Grafana.

## Overview

The monitoring stack consists of:

- **Prometheus**: Time-series database and metrics collector
- **Grafana**: Visualization and dashboard platform
- **API Metrics Endpoint**: FastAPI application exposing metrics at `/metrics`

## Architecture

```
┌─────────────┐
│   API       │ exposes /metrics
│  :8000      │◄────────────┐
└─────────────┘             │
                            │ scrapes every 10s
                            │
                    ┌───────▼──────┐
                    │  Prometheus  │
                    │    :9090     │
                    └───────┬──────┘
                            │
                            │ queries
                            │
                    ┌───────▼──────┐
                    │   Grafana    │
                    │    :3000     │
                    └──────────────┘
```

## Available Metrics

The API exposes the following Prometheus metrics:

### 1. `http_requests_total`
**Type**: Counter  
**Description**: Total count of HTTP requests  
**Labels**:
- `method`: HTTP method (GET, POST, PUT, DELETE, etc.)
- `endpoint`: Route template (e.g., `/employee/{employee_id}`)
- `status_code`: HTTP status code (200, 404, 500, etc.)

### 2. `http_request_duration_seconds`
**Type**: Histogram  
**Description**: HTTP request duration in seconds  
**Labels**: Same as `http_requests_total`  
**Buckets**: 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0

### 3. `http_errors_total`
**Type**: Counter  
**Description**: Total count of HTTP errors (status >= 400)  
**Labels**:
- `method`: HTTP method
- `endpoint`: Route template
- `status_code`: HTTP status code
- `error_type`: Either `client_error` (4xx) or `server_error` (5xx)

## Quick Start

### 1. Start the Monitoring Stack

```bash
cd integration
docker-compose up -d
```

This will start:
- Database (port 5432)
- API (port 8000)
- Prometheus (port 9090)
- Grafana (port 3000)

### 2. Access the Services

- **API Documentation**: http://localhost:8000/docs
- **API Metrics**: http://localhost:8000/metrics
- **Prometheus UI**: http://localhost:9090
- **Grafana Dashboard**: http://localhost:3000

### 3. Login to Grafana

Default credentials (can be changed in `.env`):
- Username: `admin`
- Password: `admin`

The dashboard "Estancias API Monitoring" is automatically provisioned and available.

## Grafana Dashboard

The pre-configured dashboard includes:

### Key Metrics (Top Row)
1. **Request Rate**: Total requests per second across all endpoints
2. **P95 Latency**: 95th percentile response time
3. **Error Rate**: Total errors per second

### Time Series Panels
4. **Request Rate by Endpoint**: Breakdown of traffic by endpoint and method
5. **Response Time Percentiles**: P50, P95, and P99 latency by endpoint
6. **HTTP Status Codes**: Stacked view of response status codes
7. **Error Rate by Type**: Client vs server errors by endpoint

### Table Panel
8. **Top 10 Endpoints**: Most frequently accessed endpoints

## Prometheus Queries

Here are some useful PromQL queries you can run in Prometheus or Grafana:

### Request Rate
```promql
# Total request rate
sum(rate(http_requests_total[5m]))

# Request rate by endpoint
sum(rate(http_requests_total[5m])) by (endpoint)

# Request rate by status code
sum(rate(http_requests_total[5m])) by (status_code)
```

### Latency
```promql
# P50 latency
histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

# P95 latency by endpoint
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, endpoint))

# P99 latency
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

# Average response time
sum(rate(http_request_duration_seconds_sum[5m])) / sum(rate(http_request_duration_seconds_count[5m]))
```

### Errors
```promql
# Total error rate
sum(rate(http_errors_total[5m]))

# Error rate by type
sum(rate(http_errors_total[5m])) by (error_type)

# Error rate by endpoint
sum(rate(http_errors_total[5m])) by (endpoint)

# Error percentage
sum(rate(http_errors_total[5m])) / sum(rate(http_requests_total[5m])) * 100
```

### Success Rate (SLI)
```promql
# Success rate (percentage of non-error requests)
sum(rate(http_requests_total{status_code!~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100
```

## Configuration

### Prometheus Configuration

The Prometheus configuration is in `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'estancias-api'
    static_configs:
      - targets: ['api:8000']
    metrics_path: '/metrics'
    scrape_interval: 10s
```

**Key settings**:
- `scrape_interval`: 10 seconds (how often Prometheus scrapes the API)
- `metrics_path`: `/metrics` (the endpoint where metrics are exposed)
- `targets`: `api:8000` (Docker Compose service name and port)

### Grafana Provisioning

Grafana is automatically configured using provisioning files:

- **Datasources**: `grafana/provisioning/datasources/prometheus.yml`
- **Dashboards**: `grafana/provisioning/dashboards/dashboard.yml`
- **Dashboard Definitions**: `grafana/provisioning/dashboards/definitions/api-dashboard.json`

### Environment Variables

Configure monitoring in `.env`:

```bash
# Prometheus (localhost only)
PROMETHEUS_PORT=9090

# Grafana (exposed on all interfaces)
GRAFANA_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin

# API metrics (enabled by default)
METRICS_ENABLED=true
```

## Troubleshooting

### Metrics not appearing in Prometheus

1. Check if the API metrics endpoint is working:
   ```bash
   curl http://localhost:8000/metrics
   ```

2. Check Prometheus targets status:
   - Go to http://localhost:9090/targets
   - The `estancias-api` target should be "UP"

3. Check if metrics are being collected (requires some API traffic):
   ```bash
   # Generate some traffic
   curl http://localhost:8000/docs
   
   # Query Prometheus
   curl 'http://localhost:9090/api/v1/query?query=http_requests_total'
   ```

### No data in Grafana

1. Verify Prometheus datasource:
   - Go to Configuration → Data Sources in Grafana
   - Test the Prometheus connection

2. Check if Prometheus is receiving data:
   - Go to Prometheus UI and run queries like `http_requests_total`

3. Ensure the time range in Grafana matches when the API had traffic

### Containers not starting

Check logs:
```bash
docker-compose logs prometheus
docker-compose logs grafana
docker-compose logs api
```

## Load Testing

To generate metrics for testing, you can use tools like:

### Using Apache Bench
```bash
ab -n 1000 -c 10 http://localhost:8000/docs
```

### Using hey
```bash
hey -n 1000 -c 10 http://localhost:8000/docs
```

### Using wrk
```bash
wrk -t4 -c10 -d30s http://localhost:8000/docs
```

## Best Practices

1. **Alert on SLIs**: Set up alerts based on Service Level Indicators (error rate, latency)
2. **Monitor trends**: Watch for gradual degradation over time
3. **Correlate metrics**: Look at error rates alongside latency and traffic
4. **Set up dashboards per team**: Create specific views for different audiences
5. **Regular reviews**: Periodically review which metrics are useful and which are noise

## Next Steps

For database monitoring, see the database-specific monitoring guide (coming soon).

### Potential Enhancements

- Add alerting rules in Prometheus
- Set up Alertmanager for notifications
- Add database metrics (PostgreSQL exporter)
- Add container metrics (cAdvisor)
- Set up long-term storage (Thanos or Cortex)
- Implement distributed tracing (Jaeger or Tempo)
