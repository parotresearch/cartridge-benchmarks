# One-year retention at 10 TB/day, web server logs (http_logs)

Estimate only: the cost model as a calculator, no new benchmarks. 10 TB/day, on demand, us-east-2 AWS list prices, http_logs measured sizes (the same coefficients as the 30-day scenarios). The only change is retention: 365 days searchable instead of 30 (hot/warm and hot/frozen keep 7 hot days, the rest warm/frozen: 358 days). Cartridge keeps its 7-day local cache, so only S3 storage grows.

Estimated cost per year; × is that system's cost divided by Cartridge's at the same retention.

| system | $/yr, 30 days | × | $/yr, 365 days | × |
|---|--:|--:|--:|--:|
| ES standard, all hot | $1,876,859 | 16.7× | $21,971,851 | 80.2× |
| OpenSearch 3.9 default, all hot | $1,961,039 | 17.4× | $22,909,857 | 83.6× |
| ES logsdb, free licence, all hot | $1,095,187 | 9.7× | $12,471,526 | 45.5× |
| ES hot/warm, free licence | $1,182,857 | 10.5× | $11,101,455 | 40.5× |
| ES hot/frozen, Enterprise | $756,993 | 6.7× | $2,385,892 | 8.7× |
| ES hot/frozen + logsdb, Enterprise | $381,196 | 3.4× | $767,504 | 2.8× |
| Elastic Serverless (list) | $344,151 | 3.1× | $1,067,691 | 3.9× |
| Cartridge (field data) | $112,538 | 1.0× | $273,919 | 1.0× |

## Cartridge line items at 365 days

| item | $/yr |
|---|--:|
| S3 storage (Cartridge files + field data, every tier) (637,079 GB) | $175,834 |
| build nodes (5 nodes) | $46,358 |
| query nodes (4 nodes) | $25,019 |
| S3 GET requests (36,500,000 1k requests) | $14,600 |
| EBS gp3 local copy (12,218 GB) | $11,729 |
| S3 PUT requests (upload) (75,952 1k requests) | $380 |

## Assumptions

- Query load unchanged (100K queries/day, 1,000 GETs each); query_mix and the 4 query nodes are the 30-day assumptions, not re-sized for a year of data. Frozen/warm node counts do scale with data.
- The Enterprise licence stays a flat $150K estimate. Serverless uses list-price ingest + retention for 365 days.
- Elastic's 76% logsdb factor and OpenSearch's measured ratio are from the 1× http_logs measurements, assumed to hold at a year of data.

## Command

```
uv run cost-oneyear
```

Scenarios: `cost/scenarios/10tb-365d{,-hotfrozen,-hotwarm}.yaml` (copies of the 30-day files; only retention days and name/label changed).
