# MLS Database — Schema Documentation

Comprehensive technical documentation for the **MLS (Multiple Listing Service) RDS** PostgreSQL database. This database powers the IDX data ingestion pipeline, storing MLS source metadata, ETL transformation mappings, IDX configuration rules, and normalized listing data.

---

## Schemas

| Schema | Tables | Description | Documentation |
|--------|--------|-------------|---------------|
| [`dev`](dev-schema.md) | 11 | MLS metadata catalog — source registration, resource/class/field definitions, ETL batch tracking | [Full Reference](dev-schema.md) |
| [`etl`](etl-schema.md) | 6 | ETL mapping engine — source-to-target column mappings, join conditions, Slack alerting | [Full Reference](etl-schema.md) |
| [`idx_config`](idx_config-schema.md) | 3 | IDX configuration — property type classification, school type normalization, MLS number regex | [Full Reference](idx_config-schema.md) |
| [`public`](public-schema.md) | 16 | Core listing data — listings, photos, open houses, agents, offices, property types, statuses | [Full Reference](public-schema.md) |

> **Note:** The `idx_stage` schema (staging tables for raw MLS data ingestion) is not yet included. Documentation will be added when metadata becomes available.

---

## Quick Stats

| Metric | Value |
|--------|-------|
| Total Schemas | 4 (documented) + 1 (pending) |
| Total Tables | 36 |
| Total Sequences | 25 |
| Foreign Key Constraints | 0 |
| Table Comments | 0 |
| Tables Missing Primary Keys | 5 |

---

## Architecture Overview

The MLS database follows a **multi-stage ETL pipeline** architecture:

1. **Source Registration** (`dev.source`) — MLS data sources are registered with authentication and configuration
2. **Metadata Discovery** (`dev.*_metadata`) — Resource, class, and field definitions are cataloged from each MLS source
3. **Staging** (`idx_stage.*`) — Raw MLS data is staged before transformation
4. **Transformation** (`etl.mappings`, `etl.mapping_joins`) — Source columns are mapped to target columns with business transformations
5. **Loading** (`public.listing`, etc.) — Normalized data is loaded into the public schema for consumption
6. **Configuration** (`idx_config.*`) — Property type classification, school type normalization, and MLS number formatting rules

---

## Additional Documents

| Document | Description |
|----------|-------------|
| [Database Overview](DATABASE_OVERVIEW.md) | Executive-ready architecture & schema overview |
