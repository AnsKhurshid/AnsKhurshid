# stage Schema — Post-Transformation Staging & Direct IDX Pipeline

The `stage` schema is the **post-transformation staging layer** of the MLS database. Unlike `idx_stage` (which holds raw, all-text pre-staging data), the `stage` schema contains **typed, normalized tables** that receive data after ETL transformation. It serves two major roles: housing the **Direct IDX pipeline** tables that feed the `public` schema, and providing infrastructure for the **automated mapping recommendation application**.

---

## Schema Summary

| Metric | Value |
|--------|-------|
| Tables | 58 |
| Sequences | 33 |
| Foreign Key Constraints | 3 (within `app_*` tables only) |
| CHECK Constraints | 6 |
| Tables Missing Primary Keys | 10 |
| Table Comments | 0 |

---

## Architecture Role

```
idx_stage (raw text)
        │  ETL transformation (etl.mappings)
        ▼
┌─────────────────────────────────────────┐
│           stage Schema                  │  ← YOU ARE HERE
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  Direct IDX Pipeline            │    │
│  │  direct_idx_listing (66 cols)   │    │
│  │  direct_idx_address (38 cols)   │    │
│  │  direct_idx_agent (23 cols)     │    │
│  │  direct_idx_photo (~496M rows)  │    │
│  │  direct_idx_attribute* (1200-   │    │
│  │    1600 cols, 5+ versions)      │    │
│  │  ...14 direct_idx_* tables      │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│  ┌──────────────┴──────────────────┐    │
│  │  ETL Action Queues              │    │
│  │  etl_direct_idx_insert_listings │    │
│  │  etl_direct_idx_update_listings │    │
│  │  etl_direct_idx_delete_listings │    │
│  │  etl_actions_log                │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│  ┌──────────────┴──────────────────┐    │
│  │  Mapping Recommendation App     │    │
│  │  app_users, app_jobs,           │    │
│  │  app_results, app_templates...  │    │
│  └─────────────────────────────────┘    │
└────────────────┬────────────────────────┘
                 │  Promotion
                 ▼
┌─────────────────────────────────────────┐
│  public Schema (listing, listing_photo, │
│  real_estate_participant, ...)          │
└─────────────────────────────────────────┘
```

---

## Table Groups

The 58 tables in the stage schema organize into five functional groups:

| Group | Tables | Purpose |
|-------|--------|---------|
| **Direct IDX Pipeline** | 14 | Normalized, typed staging tables for listings, addresses, agents, offices, photos, schools, brokers, attributes, descriptions |
| **ETL Action Queues** | 8 | Change-detection and action tracking — insert/update/delete queues, action logs, photo processing |
| **Mapping Recommendation App** | 12 | Automated source-to-target column mapping with ML-assisted recommendations, user management, Jira integration |
| **Data Normalization** | 5 | Area/community normalization, listing lookups, status mappings, respec counts |
| **Backup / Historical** | 7+ | Point-in-time snapshots of mappings (`mappings_838`, `mapptings_bkp_*`), attribute table backups |

---

## Direct IDX Pipeline Tables

These are the primary staging tables that hold **transformed, typed data** before it is promoted to the `public` schema. Each table represents a distinct domain entity.

### `direct_idx_listing` — Listing Core Data

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `bigint` | NO | sequence | Primary key (~19.9M rows) |
| `batch_id` | `integer` | YES | | ETL batch identifier |
| `source_id` | `integer` | YES | | MLS source reference |
| `source_listing_id` | `varchar` | YES | | Original MLS listing key |
| `price` | `numeric` | YES | | Current listing price |
| `disclose_address` | `varchar` | NO | `'1'` | IDX address disclosure flag |
| `living_area_sq_ft` | `integer` | YES | | Living area in square feet |
| `lot_size_acres` | `numeric` | YES | | Lot size in acres |
| `lot_size_sqft` | `numeric` | YES | | Lot size in square feet |
| `year_built` | `integer` | YES | | Construction year |
| `bedrooms` | `integer` | YES | | Number of bedrooms |
| `bathrooms` | `numeric` | YES | | Total bathroom count |
| `full_bathrooms` | `integer` | YES | | Full bathrooms |
| `three_quarter_bathrooms` | `integer` | YES | | Three-quarter bathrooms |
| `half_bathrooms` | `integer` | YES | | Half bathrooms |
| `one_quarter_bathrooms` | `integer` | YES | | Quarter bathrooms |
| `partial_bathrooms` | `integer` | YES | | Partial bathrooms |
| `property_type` | `varchar` | YES | | Property type classification |
| `property_sub_type` | `varchar` | YES | | Property sub-type |
| `listing_category` | `varchar` | YES | | Listing category |
| `listing_status` | `varchar` | YES | | Current status |
| `mls_number` | `varchar` | YES | | Formatted MLS number |
| `photo_count` | `integer` | YES | | Number of photos |
| `original_price` | `numeric` | YES | | Original listing price |
| `prior_price` | `numeric` | YES | | Previous price |
| `sold_price` | `numeric` | YES | | Sale price (if sold) |
| `sold_date` | `timestamptz` | YES | | Sale date |
| `expired_date` | `date` | YES | | Expiration date |
| `on_market_date` | `date` | YES | | First listed date |
| `price_type` | `varchar` | NO | `'EXACT'` | Price type (EXACT/RANGE) |
| `cumulative_days_on_market` | `integer` | YES | | Total days on market |
| `modification_timestamp` | `timestamptz` | YES | | Last MLS modification |
| `media_modification_timestamp` | `timestamptz` | YES | | Last media change |
| `source_creation_date` | `timestamptz` | YES | | Source record creation |
| `source_last_update_date` | `timestamptz` | YES | | Source last update |
| `y_creation_date` | `timestamptz` | YES | | Internal creation timestamp |
| `y_last_update_date` | `timestamptz` | YES | | Internal last update |
| `permit_address_on_internet` | `varchar` | YES | | Internet display permission |
| `vow_address_display` | `varchar` | YES | | VOW address display flag |
| `vow_automated_valuation_display` | `varchar` | YES | | VOW AVM display flag |
| `vow_consumer_comment` | `varchar` | YES | | VOW consumer comment flag |
| `disclose_map` | `boolean` | YES | | Map disclosure flag |
| `disclose_price` | `boolean` | YES | | Price disclosure flag |
| `disclose_days_on_market` | `boolean` | YES | | Days-on-market disclosure |
| `idx_contact_info` | `text` | YES | | IDX contact info (agent) |
| `idx_contact_info_office` | `text` | YES | | IDX contact info (office) |
| `source_mls_url` | `text` | YES | | Source MLS URL |

**Indexes:** PK, `batch_id`, `source_id`, `source_listing_id`, `mls_number`

---

### `direct_idx_address` — Property Addresses

38 columns. Normalized address components from MLS listings.

| Key Columns | Type | Description |
|-------------|------|-------------|
| `id` | `bigint` | Primary key (~19.5M rows) |
| `source_listing_id` | `varchar` | Links to listing |
| `street_number`, `street_name`, `street_suffix`, `street_prefix` | `varchar` | Address components |
| `full_street_address` | `varchar` | Complete street address |
| `city`, `state_or_province`, `postal_code`, `country`, `county` | `varchar` | Geographic location |
| `x_cord`, `y_cord` | `varchar` | Coordinates (stored as varchar) |
| `mls_latitude`, `mls_longitude` | `varchar` | MLS-provided coordinates |
| `community_name`, `subdivision_name` | `text` | Area names |
| `region`, `zone`, `district_name` | `text` | Regional identifiers |
| `mls_area_name`, `custom_area_name_1/2/3` | `text` | MLS-specific area names |

**Indexes:** PK, `batch_id`, `source_id`, `source_listing_id`

---

### `direct_idx_agent` — Agent/Participant Data

23 columns. Agent and participant records (~104M rows based on sequence).

| Key Columns | Type | Description |
|-------------|------|-------------|
| `id` | `bigint` | Primary key |
| `source_participant_id`, `participant_id` | `varchar` | Source and internal participant IDs |
| `first_name`, `last_name`, `full_name` | `varchar` | Name components |
| `participant_role` | `varchar` | Role (listing agent, buyer agent, etc.) |
| `primary_contact_phone`, `office_phone`, `email` | `varchar` | Contact information |
| `agent_mls_id`, `agent_mui`, `agent_license` | `varchar`/`text` | MLS identifiers |
| `rank` | `integer` | Agent rank/order on listing |

**Indexes:** PK, `batch_id`, `source_id`, `source_listing_id`

---

### `direct_idx_photo` — Listing Photos

13 columns. Photo records (~496M rows based on sequence).

| Column | Type | Description |
|--------|------|-------------|
| `id` | `bigint` | Primary key |
| `source_listing_id` | `varchar` | Links to listing |
| `media_url` | `text` | Photo URL |
| `media_modification_timestamp` | `timestamptz` | Last media change |
| `photo_order` | `integer` | Display order |
| `main_photo` | `boolean` | Primary photo flag (default `false`) |
| `pre_fetch_flag` | `boolean` | Pre-fetch indicator |

**Indexes:** PK, `batch_id`, `source_id`, `source_listing_id`

---

### `direct_idx_office` — Office Data

28 columns. Real estate office records (~690M rows based on sequence).

| Key Columns | Type | Description |
|-------------|------|-------------|
| `id` | `bigint` | Primary key |
| `source_office_id`, `office_id`, `office_mls_id`, `office_mui` | `varchar` | Office identifiers |
| `office_name`, `corporate_name` | `varchar` | Office names |
| `main_office_id` | `varchar` | Parent office reference |
| `phone_number`, `fax`, `office_email`, `website` | `varchar` | Contact info |
| `full_street_address`, `city`, `state_province`, `country`, `zipcode`, `county` | `varchar` | Address |
| `rank` | `integer` | Office rank on listing |

**Indexes:** PK, `batch_id`, `source_id`, `source_listing_id`

---

### `direct_idx_attribute` / `direct_idx_attribute_custom` — Property Attributes

These are the **widest tables in the entire database**, with 1,200 to 1,600 columns each. They store boolean property features and descriptive attributes.

| Table | Columns | PK | Rows (est.) | Notes |
|-------|---------|-----|-------------|-------|
| `direct_idx_attribute` | 1,600 | None | Unknown | Original attribute table, no PK |
| `direct_idx_attribute_2` | 1,539 | `id` | ~54M | Current standard attributes |
| `direct_idx_attribute_3` | 1,512 | `id` | ~19M | Variant/newer attributes |
| `direct_idx_attribute_custom` | 1,592 | None | Unknown | Original custom attributes, no PK |
| `direct_idx_attribute_custom_01_19_2026_bkp` | 1,592 | None | | Backup from Jan 19, 2026 |
| `direct_idx_attribute_custom_2` | 1,449 | `id` | ~4.8M | Current custom attributes |
| `direct_idx_attribute_custom_3` | 1,456 | `id` | ~5.3M | Variant custom attributes |
| `direct_idx_attribute_custom_4` | 1,215 | `id` | ~313K | Newest custom attribute version |

**Common lead columns:** `id`, `source_id`, `batch_id`, `source_listing_id`, `source_creation_date`, `source_last_update_date`, `y_creation_date`, `y_last_update_date`

**Attribute column patterns:**
- `has_*` — Boolean feature flags (e.g., `has_swimming_pool`, `has_community_boat_ramp`, `has_community_elevator`)
- `*_info` — Descriptive text for features (e.g., `swimming_pool_info`)
- `cf_a` through `cf_z` — Custom field slots (26 per source)

---

### Other Direct IDX Tables

| Table | Cols | Rows (est.) | Description |
|-------|------|-------------|-------------|
| `direct_idx_broker` | 19 | ~1.2M | Brokerage information — name, phone, email, address, logo URL |
| `direct_idx_description` | 10 | ~38.7M | Key-value pairs for listing descriptions and remarks |
| `direct_idx_id` | 6 | ~823K | Listing ID tracking with status |
| `direct_idx_openhouse` | 19 | ~21.2M | Open house events — date, time, contact, type, virtual tour URL |
| `direct_idx_openhouse_sync` | 9 | ~80K | Open house synchronization tracking |
| `direct_idx_photo_mlsgrid` | 13 | ~3.2M | MLSGrid-specific photo records (separate from main photo table) |
| `direct_idx_school` | 11 | ~44.8M | School assignments — category, name, district |
| `direct_esar_listing` | 372 | Unknown | ESAR (Eastern Sierra) source-specific listing table with all text columns |

---

## ETL Action Queue Tables

These tables manage the **change-detection pipeline** that determines which listings need to be inserted, updated, or deleted in the `public` schema.

### Insert / Update / Delete Queues

| Table | Cols | Rows (est.) | Purpose |
|-------|------|-------------|---------|
| `etl_direct_idx_insert_listings` | 7 | ~7.9M | New listings to insert into `public.listing` |
| `etl_direct_idx_update_listings` | 6 | ~2.6M | Modified listings to update |
| `etl_direct_idx_delete_listings` | 10 | ~6.3K | Listings to mark inactive/delete |
| `etl_direct_idx_missing_delete_listings` | 6 | Unknown | Missing listings flagged for deletion |

**Common columns:** `batch_id`, `source_id`, `source_listing_id`, `target_listing_id`

### Action Logging

| Table | Cols | Rows (est.) | Purpose |
|-------|------|-------------|---------|
| `etl_actions_log` | 8 | ~3.7M | Audit log of ETL actions with old/new timestamps and `action_flag` |
| `etl_action_mlsgrid_photos` | 14 | ~921K | MLSGrid photo processing queue |
| `etl_action_mlsgrid_photos_history` | 14 | ~296K | Historical photo processing records |
| `etl_mlsgrid_photos_temp` | 10 | ~1.1M | Temporary photo staging for MLSGrid |

---

## Mapping Recommendation Application

A complete **web application backend** lives within the stage schema, providing automated ETL mapping recommendations with user management, job tracking, and Jira integration.

### `app_users` — Application Users

18 columns. User accounts with role-based access.

| Key Columns | Type | Description |
|-------------|------|-------------|
| `id` | `uuid` | Primary key (auto-generated) |
| `username` | `varchar` | Unique login name |
| `password_hash` | `varchar` | Hashed password |
| `role` | `varchar` | `development`, `qa`, `production_deployment`, or `master` |
| `is_active` | `boolean` | Account status (default `true`) |
| `jira_email`, `jira_cloud_id`, `jira_account_id` | `text` | Jira integration fields |
| `jira_access_token_cipher`, `jira_refresh_token_cipher` | `text` | Encrypted Jira OAuth tokens |
| `jira_api_token_cipher` | `text` | Encrypted Jira API token |

**Constraint:** `app_users_role_check` — enforces valid role values

---

### `app_jobs` — Mapping Analysis Jobs

11 columns. Tracks automated mapping analysis runs.

| Column | Type | Description |
|--------|------|-------------|
| `id` | `uuid` | Primary key |
| `triggered_by` | `uuid` | FK to `app_users.id` |
| `source_id` | `varchar` | MLS source being analyzed |
| `status` | `varchar` | `queued` → `running` → `completed` / `failed` |
| `environment` | `varchar` | `development` or `production` |
| `total_columns` | `integer` | Total columns to map |
| `auto_recommended` | `integer` | Columns auto-mapped |
| `manual_review_count` | `integer` | Columns needing manual review |
| `flagged_count` | `integer` | Columns flagged as problematic |

**Constraints:** Status CHECK, environment CHECK  
**FK:** `triggered_by` → `app_users(id)`

---

### `app_results` — Mapping Recommendations

10 columns. Individual column-mapping recommendations per job.

| Column | Type | Description |
|--------|------|-------------|
| `id` | `uuid` | Primary key |
| `job_id` | `uuid` | FK to `app_jobs.id` |
| `target_column` | `varchar` | Target schema column |
| `source_column` | `text` | Recommended source column |
| `status` | `varchar` | `auto_recommended`, `manual_review_candidate`, `flagged_invalid_source`, `flagged_no_source` |
| `reason_code` | `varchar` | Reason for the recommendation status |
| `historical_candidates` | `jsonb` | Previous mapping candidates |

**FK:** `job_id` → `app_jobs(id)`

---

### Transformation Intelligence Tables

| Table | Cols | PK | Purpose |
|-------|------|----|---------|
| `app_transformation_templates` | 6 | `template_hash` | SQL transformation templates with AST and usage counts |
| `app_transformation_index` | 5 | Composite (3 cols) | Index of which templates apply to which source→target column pairs |
| `app_composition_rules` | 10 | `rule_id` | Rules for composing transformations based on data type, nullability, name patterns |
| `app_template_extensions` | 3 | Composite (2 cols) | Template-to-template transition tracking with counts |
| `app_suggestion_weights` | 3 | `factor` | Weighted factors for scoring mapping suggestions |
| `app_suggestion_overrides` | 6 | `id` | Manual overrides of suggested mappings |
| `app_target_column_families` | 4 | `target_column` | Column family classification (with slot group support) |
| `app_mapping_document` | 8 | `id` | Mapping documents with entry types (`CANDIDATE`, `FORCE_MANUAL_REVIEW`) |

### `app_sessions` — Express Session Store

Standard `connect-pg-simple` session store for the web application.

| Column | Type | Description |
|--------|------|-------------|
| `sid` | `varchar` | Session ID (PK) |
| `sess` | `json` | Session data |
| `expire` | `timestamp` | Expiration time |

---

## Data Normalization Tables

### `area_mapping` — Geographic Area Rules

10 columns. Maps source area expressions to normalized area names.

| Key Columns | Type | Description |
|-------------|------|-------------|
| `source_id` | `integer` | MLS source |
| `area_type` | `text` | Area classification type |
| `area_name_exp` | `text` | Source area expression/pattern |
| `area_name` | `text` | Normalized area name |
| `is_active` | `boolean` | Active flag |

### `area_normalize` — Listing Area Normalization

17 columns (~350K rows). Per-listing area normalization results.

| Key Columns | Type | Description |
|-------------|------|-------------|
| `listing_id` | `integer` | Target listing |
| `orignal_community` | `text` | Original community name (note: typo `orignal` in column name) |
| `mapped_community` | `text` | Normalized community |
| `orignal_subdivision` | `text` | Original subdivision (typo `orignal`) |
| `mapped_subdivision` | `text` | Normalized subdivision |
| `flag_address` | `integer` | Address normalization flag |

### Other Normalization Tables

| Table | Cols | Rows (est.) | Purpose |
|-------|------|-------------|---------|
| `listing_lookup` | 16 | ~3.1M | Fast listing lookup by source — price, status, timestamps, sold info |
| `ylopo_status_mapping` | 3 | Small | Maps MLS statuses to internal Ylopo status codes |
| `respecs_before_counts` | 10 | ~425 | Boolean attribute distribution BEFORE respecification |
| `respecs_after_counts` | 10 | ~292 | Boolean attribute distribution AFTER respecification |

---

## Operational & Infrastructure Tables

| Table | Cols | Rows (est.) | Purpose |
|-------|------|-------------|---------|
| `serverless_idx_loads` | 13 | ~49K | Tracks serverless ETL load runs — timestamps for last modified, full load, BL, respecs phases |
| `system_idx_resource_load` | 5 | ~723 | Tracks max modification timestamp per source/resource/class for incremental loads |
| `temp_listhub2_listings_update` | 70 | ~66K | ListHub v2 source-specific staging table with 27 indexes |

---

## Backup & Historical Tables

Several tables are point-in-time snapshots or source-specific copies with **no primary keys**:

| Table | Cols | Based On | Date |
|-------|------|----------|------|
| `mappings` | 12 | `etl.mappings` | Snapshot copy |
| `mappings_838` | 13 | `etl.mappings` | Source 838 specific |
| `mapping_joins` | 4 | `etl.mapping_joins` | Snapshot copy |
| `mapping_joins_838` | 5 | `etl.mapping_joins` | Source 838 specific |
| `mapptings_bkp_20_dec_2023` | 13 | `etl.mappings` | Dec 20, 2023 backup |
| `mapptings_bkp_21_dec_2023` | 13 | `etl.mappings` | Dec 21, 2023 backup |
| `mappting_joins_bkp_20_dec_2023` | 5 | `etl.mapping_joins` | Dec 20, 2023 backup |
| `mappting_joins_bkp_21_dec_2023` | 5 | `etl.mapping_joins` | Dec 21, 2023 backup |
| `direct_idx_attribute_custom_01_19_2026_bkp` | 1,592 | `direct_idx_attribute_custom` | Jan 19, 2026 backup |

> Note: The backup table names contain a consistent typo — `mapptings` instead of `mappings` and `mappting` instead of `mapping`.

---

## Sequences

33 sequences support auto-increment columns across the schema:

| Sequence | Last Value | Owned By |
|----------|-----------|----------|
| `direct_idx_photo_id_seq` | 496,158,102 | `direct_idx_photo.id` |
| `direct_idx_office_id_seq` | 690,620,397 | `direct_idx_office.id` |
| `direct_idx_agent_id_seq` | 104,203,170 | `direct_idx_agent.id` |
| `direct_idx_attribute_2_id_seq` | 53,956,188 | `direct_idx_attribute_2.id` |
| `direct_idx_school_id_seq` | 44,797,032 | `direct_idx_school.id` |
| `direct_idx_description_id_seq` | 38,740,178 | `direct_idx_description.id` |
| `direct_idx_openhouse_id_seq` | 21,171,814 | `direct_idx_openhouse.id` |
| `direct_idx_listing_id_seq` | 19,910,075 | `direct_idx_listing.id` |
| `direct_idx_address_id_seq` | 19,456,436 | `direct_idx_address.id` |
| `direct_idx_attribute_3_id_seq` | 19,095,813 | `direct_idx_attribute_3.id` |
| `etl_direct_idx_insert_listings_id_seq` | 7,914,966 | `etl_direct_idx_insert_listings.id` |
| `direct_idx_attribute_custom_3_id_seq` | 5,300,032 | `direct_idx_attribute_custom_3.id` |
| `direct_idx_attribute_custom_2_id_seq` | 4,774,953 | `direct_idx_attribute_custom_2.id` |
| `etl_actions_log_id_seq` | 3,698,679 | `etl_actions_log.id` |
| `direct_idx_photo_mlsgrid_id_seq` | 3,223,533 | `direct_idx_photo_mlsgrid.id` |
| `listing_lookup_id_seq` | 3,148,126 | `listing_lookup.id` |
| `etl_direct_idx_update_listings_id_seq` | 2,559,127 | `etl_direct_idx_update_listings.id` |
| `direct_idx_broker_id_seq` | 1,228,451 | `direct_idx_broker.id` |
| `etl_mlsgrid_photos_temp_id_seq` | 1,073,561 | `etl_mlsgrid_photos_temp.id` |
| `etl_action_mlsgrid_photos_id_seq` | 920,856 | `etl_action_mlsgrid_photos.id` |
| `direct_idx_id_id_seq` | 822,636 | `direct_idx_id.id` |
| `area_normalize_id_seq` | 350,404 | `area_normalize.id` |
| `direct_idx_attribute_custom_4_id_seq` | 313,359 | `direct_idx_attribute_custom_4.id` |
| `etl_action_mlsgrid_photos_history_id_seq` | 295,723 | `etl_action_mlsgrid_photos_history.id` |
| `direct_idx_openhouse_sync_id_seq` | 79,892 | Not owned |
| `temp_listhub2_listings_update_id_seq` | 65,963 | `temp_listhub2_listings_update.id` |
| `serverless_idx_loads_id_seq` | 49,161 | `serverless_idx_loads.id` |
| `etl_direct_idx_delete_listings_id_seq` | 6,321 | `etl_direct_idx_delete_listings.id` |
| `system_idx_resource_load_id_seq` | 723 | `system_idx_resource_load.id` |
| `respecs_before_counts_id_seq` | 425 | `respecs_before_counts.id` |
| `respecs_after_counts_id_seq` | 292 | `respecs_after_counts.id` |
| `suggestion_overrides_id_seq` | 1 | `app_suggestion_overrides.id` |
| `repecs_before_counts_id_seq` | — | Note: typo `repecs` in sequence name |

---

## Cross-Schema Relationships

| Related Schema | Relationship |
|----------------|-------------|
| `idx_stage.ps_*` | Source data — `stage.direct_idx_*` tables receive transformed data from pre-staging |
| `etl.mappings` | Defines transformation rules applied to populate `direct_idx_*` tables |
| `etl.mapping_joins` | JOIN conditions for multi-table transformations |
| `dev.source` | `source_id` in all staging tables references `dev.source.source_id` |
| `dev.etl_batches` | `batch_id` tracks which ETL run loaded the data |
| `public.listing` | Target for `direct_idx_listing` data after promotion |
| `public.listing_photo` | Target for `direct_idx_photo` data |
| `public.real_estate_participant` | Target for `direct_idx_agent` data |
| `public.real_estate_office` | Target for `direct_idx_office` data |
| `public.listing_school` | Target for `direct_idx_school` data |
| `idx_config.listing_property_type` | Property type classification applied during staging |

---

## Design Patterns

### Vertically-Partitioned Entity Model
Rather than a single wide listing table, the stage schema splits listing data into **domain-specific tables** (`direct_idx_listing`, `direct_idx_address`, `direct_idx_agent`, etc.), linked by `source_listing_id`. This enables:
- Independent update cycles per domain
- Parallel ETL processing
- Manageable table widths (except attributes)

### Version-Suffixed Tables
Attribute tables (`direct_idx_attribute`, `_2`, `_3`, `_custom`, `_custom_2`, `_custom_3`, `_custom_4`) represent **schema evolution**. New versions are created as attribute requirements change, while older versions are retained for backward compatibility.

### Change-Detection Queues
The `etl_direct_idx_insert/update/delete_listings` tables implement a **queue-based CDC pattern** where the ETL process identifies changes and queues them as explicit insert/update/delete actions before applying them to the `public` schema.

### Dual Timestamp Convention
All staging tables carry four timestamp columns:
- `source_creation_date` / `source_last_update_date` — From the MLS source
- `y_creation_date` / `y_last_update_date` — Internal pipeline timestamps

### Application-in-Database
The `app_*` tables constitute a complete web application backend stored within the database schema, including user auth, session management, job tracking, and Jira integration — a pattern where the database serves as both data store and application state.

---

## Known Issues & Observations

- **Tables without primary keys (10):** `direct_idx_attribute`, `direct_idx_attribute_custom`, `direct_idx_attribute_custom_01_19_2026_bkp`, `mappings`, `mappings_838`, `mapping_joins`, `mapping_joins_838`, `mapptings_bkp_20_dec_2023`, `mapptings_bkp_21_dec_2023`, `mappting_joins_bkp_20_dec_2023`, `mappting_joins_bkp_21_dec_2023`
- **Column name typos:** `orignal_community` and `orignal_subdivision` in `area_normalize` (should be `original`)
- **Table name typos:** `mapptings_bkp_*` (double "p") and `mappting_joins_bkp_*`
- **Sequence name typo:** `repecs_before_counts_id_seq` (should be `respecs`)
- **Ultra-wide tables:** Attribute tables with 1,200–1,600 columns may impact query planning, `pg_dump` performance, and TOAST overhead
- **Orphaned sequence:** `direct_idx_openhouse_sync_id_seq` has no `owned_by` relationship
- **Jira credentials in database:** `app_users` stores encrypted Jira tokens — ensure encryption keys are properly managed
- **Backup table accumulation:** Multiple dated backup tables suggest manual backup practices rather than automated versioning
- **Coordinate storage:** Latitude/longitude stored as `varchar` in `direct_idx_address` rather than `numeric` or `geometry`
