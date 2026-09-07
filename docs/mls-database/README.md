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
| [`stage`](stage-schema.md) | 58 | Post-transformation staging — Direct IDX pipeline, ETL action queues, mapping recommendation app | [Full Reference](stage-schema.md) |
| [`idx_stage`](idx_stage-schema.md) | Hundreds | Pre-staging raw data — one all-text table per source/resource (`ps_{type}_{resource}_{source_id}`) | [Full Reference](idx_stage-schema.md) |

---

## Quick Stats

| Metric | Value |
|--------|-------|
| Total Schemas | 6 |
| Total Tables | 94 + hundreds (idx_stage) |
| Total Sequences | 58 |
| Foreign Key Constraints | 0 |
| Table Comments | 0 |
| Tables Missing Primary Keys | 15 |

---

## Architecture Overview

The MLS database follows a **multi-stage ETL pipeline** architecture:

1. **Source Registration** (`dev.source`) — MLS data sources are registered with authentication and configuration
2. **Metadata Discovery** (`dev.*_metadata`) — Resource, class, and field definitions are cataloged from each MLS source
3. **Pre-Staging** (`idx_stage.*`) — Raw MLS data is downloaded into all-text tables (`ps_{type}_{resource}_{source_id}`)
4. **Transformation** (`etl.mappings`, `etl.mapping_joins`) — Source columns are mapped to target columns with business transformations
5. **Post-Transformation Staging** (`stage.*`) — Transformed, typed data lands in Direct IDX pipeline tables with change-detection queues
6. **Loading** (`public.listing`, etc.) — Normalized data is promoted from stage to the public schema for consumption
7. **Configuration** (`idx_config.*`) — Property type classification, school type normalization, and MLS number formatting rules

---

## Additional Documents

| Document | Description |
|----------|-------------|
| [Database Overview](DATABASE_OVERVIEW.md) | Executive-ready architecture & schema overview |
