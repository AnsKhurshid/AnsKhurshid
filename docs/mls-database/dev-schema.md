# dev Schema — MLS Metadata Catalog

The `dev` schema serves as the **metadata catalog** for the MLS data ingestion pipeline. It tracks MLS data sources, their resources (API endpoints), classes (data categories), and individual field definitions. This schema provides the configuration backbone that drives the ETL process.

---

## Schema Summary

| Metric | Value |
|--------|-------|
| Tables | 11 |
| Sequences | 10 |
| Foreign Keys | 0 |
| Table Comments | 0 |

---

## Table of Contents

1. [source](#1-source)
2. [resource_metadata](#2-resource_metadata)
3. [resource_prefix](#3-resource_prefix)
4. [class_metadata](#4-class_metadata)
5. [field_metadata](#5-field_metadata)
6. [stage_resource_metadata](#6-stage_resource_metadata)
7. [stage_class_metadata](#7-stage_class_metadata)
8. [stage_field_metadata](#8-stage_field_metadata)
9. [etl_batches](#9-etl_batches)
10. [enum_status](#10-enum_status)
11. [to_do](#11-to_do)

---

## Tables

### 1. source

MLS data source registry. Each row represents a distinct MLS provider with authentication details and configuration.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | NO | | MLS source identifier |
| `source_name` | varchar | YES | | Human-readable source name |
| `auth` | varchar | YES | | Authentication configuration |
| `creation_date` | date | YES | | Date source was registered |
| `is_active` | boolean | YES | | Whether source is currently active |
| `resource_prefix` | varchar | YES | | URL/API prefix for this source |
| `source_system_ids` | varchar | YES | | External system identifiers |
| `source_type` | varchar | YES | | Source protocol type (e.g., RETS, Web API) |

**Primary Key:** `id`
**Indexes:** `source_pk` (btree on `id`)
**Estimated Rows:** ~34

---

### 2. resource_metadata

Tracks API resources (endpoints/tables) available from each MLS source.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Denormalized source name |
| `resource_name` | varchar | YES | | Resource/endpoint name |
| `resource_description` | varchar | YES | | Human-readable description |
| `keyfield` | varchar | YES | | Primary key field for this resource |
| `active_flag` | boolean | YES | `true` | Whether resource is active |
| `download_flag` | boolean | YES | `true` | Whether to download this resource |
| `critical_flag` | boolean | YES | `false` | Whether resource is critical |
| `y_creation_date` | timestamp | YES | `now()` | Internal creation timestamp |
| `y_updation_date` | timestamp | YES | `now()` | Internal last-update timestamp |

**Primary Key:** `id`
**Indexes:** `resource_metadata_pkey` (btree on `id`)
**Estimated Rows:** ~4,556

---

### 3. resource_prefix

Maps MLS sources to resource-specific URL prefixes.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Denormalized source name |
| `resource_name` | varchar | YES | | Resource name |
| `prefix` | varchar | YES | | URL prefix for this resource |

**Primary Key:** `id`
**Indexes:** `resource_prefix_pkey` (btree on `id`)
**Estimated Rows:** ~9

---

### 4. class_metadata

Tracks data classes (categories) within each MLS resource.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Denormalized source name |
| `resource_name` | varchar | YES | | Parent resource name |
| `class_name` | varchar | YES | | Class identifier |
| `standard_name` | varchar | YES | | RESO standard name |
| `visible_name` | varchar | YES | | Display name |
| `description` | varchar | YES | | Class description |
| `key_date` | date | YES | `now()::date` | Key date for incremental pulls |
| `active_flag` | boolean | YES | `true` | Whether class is active |
| `download_flag` | boolean | YES | `true` | Whether to download this class |
| `critical_flag` | boolean | YES | `false` | Whether class is critical |
| `y_creation_date` | timestamp | YES | `now()` | Internal creation timestamp |
| `y_updation_date` | timestamp | YES | `now()` | Internal last-update timestamp |
| `respecs_download_flag` | boolean | YES | `true` | Re-specification download flag |

**Primary Key:** `id`
**Indexes:** `class_metadata_pkey` (btree on `id`)
**Estimated Rows:** ~18,854

---

### 5. field_metadata

Detailed field-level metadata for each MLS class. The largest table in the `dev` schema.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Denormalized source name |
| `resource_name` | varchar | YES | | Parent resource name |
| `class_name` | varchar | YES | | Parent class name |
| `long_name` | varchar | YES | | Original field name from MLS |
| `renamed_long_name` | varchar | YES | | Ylopo-renamed field name |
| `rename_flag` | boolean | YES | `false` | Whether field has been renamed |
| `db_name` | varchar | YES | | Database column name |
| `system_name` | varchar | YES | | System-level field name |
| `max_length` | varchar | YES | | Maximum field length |
| `datatype` | varchar | YES | | Field data type |
| `key_value` | varchar | YES | `now()::date` | Key value for lookups |
| `active_flag` | boolean | YES | `true` | Whether field is active |
| `download_flag` | boolean | YES | `true` | Whether to download this field |
| `critical_flag` | boolean | YES | `false` | Whether field is critical |
| `y_creation_date` | timestamp | YES | `now()` | Internal creation timestamp |
| `y_updation_date` | timestamp | YES | `now()` | Internal last-update timestamp |
| `status_flag` | boolean | YES | `true` | Field status |
| `foreign_field` | text | YES | | Referenced foreign field |
| `lookup_name` | text | YES | | Lookup table name |
| `respecs_download_flag` | boolean | YES | `true` | Re-specification download flag |

**Primary Key:** `id`
**Indexes:** `field_metadata_2_pkey` (btree on `id`)
**Estimated Rows:** ~3,774,159

---

### 6. stage_resource_metadata

Staging version of resource metadata. Resources are first loaded here during MLS metadata discovery before being promoted to `resource_metadata`.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Denormalized source name |
| `resource_name` | varchar | YES | | Resource name |
| `resource_description` | varchar | YES | | Resource description |
| `keyfield` | varchar | YES | | Primary key field |
| `active_flag` | boolean | YES | `true` | Whether active |
| `y_creation_date` | timestamp | YES | `now()` | Creation timestamp |

**Primary Key:** `id`
**Indexes:** `stage_resource_metadata_pkey` (btree on `id`)
**Estimated Rows:** ~16,125

---

### 7. stage_class_metadata

Staging version of class metadata. Classes are staged here before promotion to `class_metadata`.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Denormalized source name |
| `resource_name` | varchar | YES | | Parent resource name |
| `class_name` | varchar | YES | | Class identifier |
| `standard_name` | varchar | YES | | RESO standard name |
| `visible_name` | varchar | YES | | Display name |
| `description` | varchar | YES | | Class description |
| `key_date` | date | YES | `'2023-01-01'` | Default key date |
| `active_flag` | boolean | YES | `true` | Whether active |
| `y_creation_date` | timestamp | YES | `now()` | Creation timestamp |

**Primary Key:** `id`
**Indexes:** `stage_class_metadata_pkey` (btree on `id`)
**Estimated Rows:** ~65,080

---

### 8. stage_field_metadata

Staging version of field metadata. Fields are staged here before promotion to `field_metadata`. The largest table in the entire database.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Denormalized source name |
| `resource_name` | varchar | YES | | Parent resource name |
| `class_name` | varchar | YES | | Parent class name |
| `long_name` | varchar | YES | | Original field name |
| `renamed_long_name` | varchar | YES | | Renamed field name |
| `rename_flag` | boolean | YES | `false` | Whether renamed |
| `db_name` | varchar | YES | | Database column name |
| `system_name` | varchar | YES | | System-level name |
| `max_length` | varchar | YES | | Max field length |
| `datatype` | varchar | YES | | Data type |
| `key_value` | varchar | YES | | Key value |
| `active_flag` | boolean | YES | `true` | Whether active |
| `download_flag` | boolean | YES | `true` | Whether to download |
| `critical_flag` | boolean | YES | `false` | Whether critical |
| `y_creation_date` | timestamp | YES | `now()` | Creation timestamp |
| `y_updation_date` | timestamp | YES | `now()` | Last-update timestamp |
| `status_flag` | boolean | YES | `true` | Field status |
| `lookup_name` | text | YES | | Lookup table name |
| `foreign_field` | text | YES | | Referenced foreign field |

**Primary Key:** `id`
**Indexes:** `stage_field_metadata_2_pkey` (btree on `id`)
**Estimated Rows:** ~6,013,635

---

### 9. etl_batches

Tracks ETL batch execution runs — each row represents a download/load cycle for an MLS source.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source (convention-based) |
| `source_name` | varchar | YES | | Source name |
| `batch_id` | integer | YES | | Batch run identifier |
| `batch_start_time` | timestamp | YES | | Batch start timestamp |
| `batch_end_time` | timestamp | YES | | Batch end timestamp |
| `download_status` | varchar | YES | | Download phase status |
| `loading_status` | varchar | YES | | Loading phase status |
| `creation_date` | date | YES | | Record creation date |

**Primary Key:** `id`
**Indexes:** `etl_batches_pkey` (btree on `id`)
**Estimated Rows:** ~80

---

### 10. enum_status

Lookup table for status enumeration values.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | | Status identifier |
| `status` | varchar | YES | | Status label |

**Primary Key:** `id`
**Indexes:** `enum_status_pkey` (btree on `id`)

---

### 11. to_do

Task queue for MLS data download and loading operations. Each row represents a work item for a specific source/resource/class combination.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `source_id` | integer | YES | | FK to source |
| `status` | varchar | YES | | Current task status |
| `status_description` | varchar | YES | | Status details |
| `source_name` | varchar | YES | | Source name |
| `login_url` | varchar | YES | | MLS login URL |
| `username` | varchar | YES | | MLS login username |
| `password` | varchar | YES | | MLS login password |
| `resource_name` | varchar | YES | | Target resource |
| `classname` | varchar | YES | | Target class |
| `creation_date` | date | YES | | Task creation date |
| `filter_criteria` | varchar | YES | | Download filter criteria |
| `column_normalized` | text | YES | | Normalized column list |
| `long_name_normalized` | text | YES | | Normalized long name list |
| `batch_id` | integer | YES | | Associated batch ID |
| `download_status` | varchar | YES | | Download status |
| `download_start_time` | timestamp | YES | | Download start |
| `download_end_time` | timestamp | YES | | Download end |
| `loading_status` | varchar | YES | | Loading status |
| `loading_start_time` | timestamp | YES | | Loading start |
| `loading_end_time` | timestamp | YES | | Loading end |
| `source_type` | varchar | YES | | Source protocol type |
| `job_type` | varchar | YES | | Job type identifier |

**Primary Key:** `id`
**Indexes:** `to_do_pkey` (btree on `id`)
**Estimated Rows:** ~1,780

---

## Sequences

| Sequence | Owned By | Last Value |
|----------|----------|------------|
| `class_metadata_id_seq` | `class_metadata.id` | 18,854 |
| `etl_batches_id_seq` | `etl_batches.id` | 80 |
| `field_metadata_2_id_seq` | `field_metadata.id` | 3,774,159 |
| `resource_metadata_id_seq` | `resource_metadata.id` | 4,556 |
| `resource_prefix_id_seq` | `resource_prefix.id` | 9 |
| `source_id_seq` | `source.id` | 34 |
| `stage_class_metadata_id_seq` | `stage_class_metadata.id` | 65,080 |
| `stage_field_metadata_2_id_seq` | `stage_field_metadata.id` | 6,013,635 |
| `stage_resource_metadata_id_seq` | `stage_resource_metadata.id` | 16,125 |
| `to_do_id_seq` | `to_do.id` | 1,780 |

---

## Design Patterns

### Stage-Promote Pattern
The schema implements a **stage-promote** pattern for metadata ingestion:
- `stage_resource_metadata` → `resource_metadata`
- `stage_class_metadata` → `class_metadata`
- `stage_field_metadata` → `field_metadata`

Raw metadata from MLS sources is first loaded into `stage_*` tables, validated, then promoted to the production `*_metadata` tables. The staging tables have ~3x more rows than their production counterparts, suggesting historical staging data is retained.

### Denormalized Source Names
Every table carries both `source_id` and `source_name`, avoiding joins to the `source` table at the cost of data redundancy. This is a deliberate trade-off for query simplicity in an ETL context.

### Flag-Based Control
Multiple boolean flags (`active_flag`, `download_flag`, `critical_flag`, `status_flag`, `respecs_download_flag`) provide fine-grained control over which metadata elements participate in the ETL pipeline.
