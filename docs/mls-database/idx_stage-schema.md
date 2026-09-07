# idx_stage Schema — Pre-Staging Raw Data

The `idx_stage` schema contains **pre-staging tables** that hold raw data downloaded directly from MLS sources. This is the first landing zone in the ETL pipeline — data arrives here in its original form before any transformation or type casting occurs.

---

## Schema Summary

| Metric | Value |
|--------|-------|
| Tables | Hundreds (one per source/resource combination) |
| Column Data Types | All `text` (no type casting at this stage) |
| Foreign Keys | 0 |
| Table Comments | 0 |

---

## Architecture Role

```
MLS Sources (RETS / Web API)
        │
        ▼
┌─────────────────────────────┐
│      idx_stage Schema       │  ← YOU ARE HERE
│                             │
│  ps_rets_property_101       │  Raw RETS data
│  ps_rets_office_101         │
│  ps_rets_agent_101          │
│  ps_api_property_205        │  Raw API data
│  ps_api_member_205          │
│  ...hundreds more...        │
└────────────┬────────────────┘
             │  ETL transformation
             │  (etl.mappings)
             ▼
┌─────────────────────────────┐
│      public Schema          │  Normalized, typed data
│  listing, listing_photo...  │
└─────────────────────────────┘
```

---

## Table Naming Convention

Every table in `idx_stage` follows a strict naming pattern based on the source protocol:

### API Sources

```
ps_{source_type}_{resource_name}_{source_id}
```

| Component | Description | Example |
|-----------|-------------|---------|
| `ps_` | Pre-staging prefix | — |
| `{source_type}` | API protocol type (e.g., `api`, `webapi`, `odata`) | `api` |
| `{resource_name}` | MLS resource/endpoint name | `property`, `member`, `office`, `openhouse` |
| `{source_id}` | Numeric source identifier from `dev.source` | `205` |

**Examples:**
- `ps_api_property_205` — Property listings from API source 205
- `ps_api_member_205` — Agent/member data from API source 205
- `ps_api_office_205` — Office data from API source 205
- `ps_api_openhouse_205` — Open house events from API source 205

### RETS Sources

```
ps_rets_{resource_name}_{source_id}
```

| Component | Description | Example |
|-----------|-------------|---------|
| `ps_` | Pre-staging prefix | — |
| `rets` | RETS protocol identifier | — |
| `{resource_name}` | RETS resource name | `property`, `office`, `agent` |
| `{source_id}` | Numeric source identifier from `dev.source` | `101` |

**Examples:**
- `ps_rets_property_101` — Property listings from RETS source 101
- `ps_rets_office_101` — Office data from RETS source 101
- `ps_rets_agent_101` — Agent data from RETS source 101

---

## Column Design

All columns in every `idx_stage` table use the `text` data type regardless of the actual data they contain. This is a deliberate design choice:

- **No type casting failures** — Raw MLS data can contain unexpected formats, nulls represented as strings, or non-standard values. Using `text` ensures no data is lost during the download phase.
- **Source fidelity** — The pre-staging layer preserves the exact data as received from the MLS, without any interpretation or transformation.
- **Deferred validation** — Type casting, validation, and transformation happen downstream in the ETL pipeline (driven by `etl.mappings`) when data moves to the `public` schema.

### Typical Column Sources

Columns in each pre-staging table correspond to the fields defined in `dev.field_metadata` for that source/resource/class combination. The column names typically match the MLS field names (either `long_name` or `db_name` from `field_metadata`).

---

## Table Volume Estimation

Based on the metadata catalog:

| Metric | Value | Source |
|--------|-------|--------|
| MLS Sources | ~34 | `dev.source` sequence last_value |
| Resources per Source | ~134 avg | `dev.resource_metadata` / sources |
| Active Resources | Varies | Controlled by `download_flag` |
| Metadata File Size | ~47 MB | Schema metadata export |

The 47MB metadata file and the resource counts suggest **several hundred tables** in `idx_stage`, each with potentially hundreds of text columns matching the MLS field definitions.

---

## Data Flow

### Inbound: Download Phase

1. The ETL scheduler creates a task in `dev.to_do` for each source/resource/class combination
2. Data is downloaded from the MLS source via RETS or Web API protocol
3. Raw records are inserted into the corresponding `ps_*` table with all values as `text`
4. The `batch_id` tracks which ETL run loaded the data
5. Download status is recorded in `dev.etl_batches`

### Outbound: Transformation Phase

1. `etl.mappings` defines how each `ps_*` column maps to a `public.*` target column
2. `etl.mapping_joins` provides JOIN conditions when multiple `ps_*` tables need to be combined
3. Business transformations (type casting, value normalization, lookups) are applied during the move
4. Transformed data lands in `public.listing`, `public.real_estate_participant`, etc.

---

## Cross-Schema Relationships

| Related Schema | Relationship |
|----------------|-------------|
| `dev.source` | `source_id` in table names links to `dev.source.source_id` |
| `dev.field_metadata` | Column names correspond to `field_metadata.db_name` or `long_name` |
| `dev.resource_metadata` | `resource_name` in table names matches `resource_metadata.resource_name` |
| `etl.mappings` | `source_table` in mappings references `idx_stage` table names |
| `etl.mapping_joins` | JOIN conditions reference `idx_stage` tables |
| `public.*` | Target tables for transformed data |

---

## Design Patterns

### One Table Per Source-Resource
Rather than using a single staging table with a `source_id` column, the schema creates **dedicated tables per source/resource**. This provides:
- **Isolation** — One source's schema changes don't affect others
- **Independent column sets** — Each MLS source has different fields; dedicated tables avoid sparse columns
- **Parallel loading** — Multiple sources can load simultaneously without contention
- **Easy cleanup** — Dropping a source's data means dropping its tables

### All-Text Columns
The universal `text` type eliminates type-mismatch errors during bulk loading. This is a common pattern in ELT (Extract-Load-Transform) architectures where raw data is loaded first and transformed later, as opposed to ETL where transformation happens before loading.

### Convention-Based Naming
The `ps_{type}_{resource}_{id}` naming convention serves as implicit metadata — the source type, resource, and source ID can be parsed directly from the table name without querying a lookup table. This simplifies the ETL orchestration logic.

---

## Operational Notes

- **Table proliferation** — As new MLS sources are onboarded, new `ps_*` tables are automatically created. Decommissioned sources may leave orphaned tables.
- **Column evolution** — When an MLS source adds or removes fields, the corresponding `ps_*` table columns need to be updated. This is driven by the metadata discovery process (`dev.stage_field_metadata` → `dev.field_metadata`).
- **No indexes expected** — Pre-staging tables typically have minimal or no indexes, as they are write-heavy during download and read sequentially during transformation.
- **Data retention** — Pre-staging data may be truncated or replaced on each ETL batch run, depending on the pipeline configuration.
