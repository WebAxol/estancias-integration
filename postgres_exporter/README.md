# PostgreSQL Monitoring with Prometheus

This directory contains the configuration for monitoring PostgreSQL using the postgres_exporter.

## Overview

The postgres_exporter collects various PostgreSQL metrics and exposes them in a format that Prometheus can scrape. These metrics provide insights into:

- Database size and growth
- Table and index sizes
- Connection statistics
- Transaction performance
- Cache hit ratios
- Query performance
- Replication status (if applicable)

## Configuration

### queries.yaml

The `queries.yaml` file defines custom queries that extend the default metrics collected by postgres_exporter. The queries include:

1. **pg_database_size**: Size of each database in bytes
2. **pg_table_stats**: Table sizes, index sizes, and tuple counts
3. **pg_connection_stats**: Connection counts by state (active, idle, etc.)
4. **pg_transaction_stats**: Transaction commits, rollbacks, and tuple operations
5. **pg_index_usage**: Index usage statistics to identify unused indexes
6. **pg_cache_hit_ratio**: Buffer cache hit ratio percentage
7. **pg_slow_queries**: Currently running queries that take more than 1 second
8. **pg_replication_lag**: Replication lag for replica servers

## Metrics Endpoints

- **PostgreSQL Exporter**: http://localhost:9187/metrics
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

## Default Metrics

In addition to custom queries, postgres_exporter automatically collects:

- `pg_up`: Whether the PostgreSQL server is up
- `pg_stat_database_*`: Database-level statistics
- `pg_stat_bgwriter_*`: Background writer statistics
- `pg_locks_*`: Lock information
- `pg_settings_*`: PostgreSQL configuration settings

## Useful PromQL Queries

### Cache Hit Ratio
```promql
100 * sum(rate(pg_stat_database_blks_hit{datname="estancias"}[5m])) / 
(sum(rate(pg_stat_database_blks_hit{datname="estancias"}[5m])) + 
 sum(rate(pg_stat_database_blks_read{datname="estancias"}[5m])))
```

### Active Connections
```promql
pg_connection_stats_active_connections
```

### Database Size Growth Rate
```promql
rate(pg_database_size_size_bytes[1h])
```

### Transaction Rate
```promql
rate(pg_transaction_stats_commits[5m])
```

### Rollback Ratio
```promql
rate(pg_transaction_stats_rollbacks[5m]) / 
(rate(pg_transaction_stats_commits[5m]) + rate(pg_transaction_stats_rollbacks[5m]))
```

## Grafana Dashboards

You can import pre-built PostgreSQL dashboards from Grafana:

1. **PostgreSQL Database** (ID: 9628)
2. **PostgreSQL Overview** (ID: 455)
3. **PostgreSQL Exporter Quickstart** (ID: 14114)

To import:
1. Go to Grafana (http://localhost:3000)
2. Click "+" → "Import"
3. Enter the dashboard ID
4. Select Prometheus as the data source
5. Click "Import"

## Security Notes

- The postgres_exporter connects using credentials from the .env file
- The exporter port (9187) is bound to localhost only for security
- Ensure POSTGRES_PASSWORD is changed from the default value in production

## Troubleshooting

### Check if exporter is running
```bash
docker logs estancias-postgres-exporter
```

### Test metrics endpoint
```bash
curl http://localhost:9187/metrics
```

### Verify Prometheus is scraping
Go to Prometheus (http://localhost:9090) → Status → Targets
Look for the "postgresql" job - it should show as "UP"

### Check custom query syntax
If a custom query fails, check the logs:
```bash
docker logs estancias-postgres-exporter | grep ERROR
```
