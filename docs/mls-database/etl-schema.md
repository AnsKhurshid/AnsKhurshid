# etl Schema — ETL Mapping Engine

The `etl` schema contains the **transformation mapping engine** that drives the MLS data pipeline. It defines how source columns from MLS feeds map to target columns in the normalized data model, including join conditions, business transformations, and operational alerting.

---

## Schema Summary

| Metric | Value |
|--------|-------|
| Tables | 6 (including 2 backups) |
| Sequences | 5 |
| Foreign Keys | 0 |
| Table Comments | 0 |

---

## Table of Contents

1. [mappings](#1-mappings)
2. [mapping_joins](#2-mapping_joins)
3. [source_info](#3-source_info)
4. [slack_alerts](#4-slack_alerts)
5. [mappings_backup](#5-mappings_backup)
6. [mappings_backup_29_jan_2024](#6-mappings_backup_29_jan_2024)

---

## Tables

### 1. mappings

Core mapping table defining source-to-target column transformations. Each row maps a single source column (or multi-column expression) from an MLS feed to a target column in the normalized schema.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | MLS source identifier |
| `resource_name` | varchar | YES | | MLS resource name |
| `target_table` | varchar | YES | | Destination table name |
| `target_column` | varchar | YES | | Destination column name |
| `source_table` | varchar | YES | | Source table/resource |
| `source_column` | text | YES | `'multi col'` | Source column name or expression |
| `status` | boolean | YES | `true` | Whether mapping is active |
| `created_date` | date | YES | `now()` | Mapping creation date |
| `previous_id` | integer | YES | | Link to previous version of this mapping |
| `business_transformation` | text | YES | | SQL/logic for data transformation |
| `reference_id` | integer | YES | | Reference to related mapping |
| `shared_source_type` | text | YES | | Source type for shared mappings |

**Primary Key:** `id`
**Indexes:** `mappings_pkey` (btree on `id`)
**Estimated Rows:** ~355,283

---

### 2. mapping_joins

Defines SQL JOIN conditions needed to resolve multi-table mappings. Used in conjunction with `mappings` to construct complete ETL queries.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | bigint | YES | | MLS source identifier |
| `resource_name` | varchar | YES | | MLS resource name |
| `joins_and_conditions` | varchar | YES | | SQL JOIN clause(s) |
| `shared_source_type` | text | YES | | Source type for shared joins |

**Primary Key:** `id`
**Indexes:** `mapping_joins_pkey` (btree on `id`)
**Estimated Rows:** ~7,617

---

### 3. source_info

Stores per-source IDX configuration as JSON. Provides source-specific settings for the data pipeline.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | MLS source identifier |
| `idx_info` | json | YES | | JSON blob with IDX configuration |

**Primary Key:** `id`
**Unique Constraint:** `source_id_unique` on (`source_id`)
**Indexes:** `source_info_pkey` (btree on `id`), `source_id_unique` (unique btree on `source_id`)
**Estimated Rows:** ~117

---

### 4. slack_alerts

Configurable SQL-based alerts that post to Slack channels when ETL anomalies are detected.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `title` | text | NO | | Alert title/name |
| `sql_query` | text | NO | | SQL query to evaluate alert condition |
| `active` | boolean | NO | `true` | Whether alert is active |
| `threshold_runs` | integer | NO | `4` | Number of consecutive triggers before alerting |
| `last_executed` | timestamptz | YES | | Last execution timestamp |
| `slack_channal` | text | YES | | Target Slack channel *(note: column name has typo)* |
| `created_at` | timestamptz | YES | `now()` | Record creation timestamp |
| `updated_at` | timestamptz | YES | `now()` | Record update timestamp |

**Primary Key:** `id`
**Indexes:** `slack_alerts_pkey` (btree on `id`), `idx_slack_alerts_active_lastexec` (btree on `active`, `last_executed`)

---

### 5. mappings_backup

Full backup of the `mappings` table. Same structure as `mappings` but without auto-increment or primary key.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | |
| `source_id` | integer | YES | |
| `resource_name` | varchar | YES | |
| `target_table` | varchar | YES | |
| `target_column` | varchar | YES | |
| `source_table` | varchar | YES | |
| `source_column` | varchar | YES | |
| `status` | boolean | YES | |
| `created_date` | date | YES | |
| `previous_id` | integer | YES | |
| `business_transformation` | text | YES | |
| `reference_id` | integer | YES | |
| `shared_source_type` | text | YES | |

**Primary Key:** *None*
**Indexes:** *None*

---

### 6. mappings_backup_29_jan_2024

Point-in-time backup of `mappings` from January 29, 2024. Same structure but with `id` nullable and no constraints.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `source_id` | integer | YES | |
| `resource_name` | varchar | YES | |
| `target_table` | varchar | YES | |
| `target_column` | varchar | YES | |
| `source_table` | varchar | YES | |
| `source_column` | varchar | YES | |
| `status` | boolean | YES | |
| `created_date` | date | YES | |
| `previous_id` | integer | YES | |
| `business_transformation` | text | YES | |
| `reference_id` | integer | YES | |
| `shared_source_type` | text | YES | |
| `id` | integer | YES | |

**Primary Key:** *None*
**Indexes:** *None*

---

## Sequences

| Sequence | Owned By | Last Value |
|----------|----------|------------|
| `mapping_joins_seq` | `mapping_joins.id` | 7,617 |
| `mappings_backup_id_seq` | *(orphaned)* | 2 |
| `mappings_new_id_seq` | `mappings.id` | 355,283 |
| `slack_alerts_id_seq` | `slack_alerts.id` | *(unused)* |
| `source_info_id_seq` | `source_info.id` | 117 |

---

## Design Patterns

### Mapping Versioning
The `mappings.previous_id` column creates a **linked-list version chain**, allowing the system to track how column mappings evolve over time. When a mapping is updated, the old version is preserved and the new row points back to it.

### Shared Source Types
Both `mappings` and `mapping_joins` support a `shared_source_type` column, enabling a single mapping definition to be reused across multiple MLS sources that share the same data format.

### SQL-Driven Alerting
The `slack_alerts` table implements a **query-based monitoring** pattern — each alert is a raw SQL query that the system evaluates periodically. The `threshold_runs` column prevents alert fatigue by requiring multiple consecutive trigger evaluations before posting to Slack.

### Backup Strategy
Two backup tables preserve historical mapping snapshots. The dated backup (`_29_jan_2024`) suggests periodic manual backups are taken before major mapping changes.

---

## Known Issues

- **Typo in column name:** `etl.slack_alerts.slack_channal` should be `slack_channel`
- **Orphaned sequence:** `mappings_backup_id_seq` has no `owned_by` association
- **Backup tables lack constraints:** No primary keys or indexes on backup tables, making them unsuitable for lookups
