This directory contains a ClickHouse docker compose stack and a Python script to investigate a data duplication issue.

## ClickHouse architecture

A cluster `test_cluster` is configured with 2 shards. Each shard has 2 replicas.

`internal_replication` is set to `true`

## How-to

To reproduce the issue:

1. Start the ClickHouse cluster: `docker compose up`
2. Execute the Python script: `poetry run python duplicate_counts.py`

You should see several log lines starting with `Different count`.