# HomelistingDB Architecture & Schema Documentation

**High-Level Technical Overview for Stakeholders & Developers**

**Author:** IDX Team

---

## Table of Contents

1. [Executive Summary & System Purpose](#1-executive-summary--system-purpose)
2. [Architectural Overview](#2-architectural-overview)
   - [Multi-MLS Ingestion Pipeline](#multi-mls-ingestion-pipeline)
   - [Compliance & Display Rules](#compliance--display-rules)
   - [Geocoding & Spatial Pipeline](#geocoding--spatial-pipeline)
   - [Active Search vs. Historical Archive](#active-search-vs-historical-archive)
3. [Schema Analysis: `public`](#3-schema-analysis-public)
   - [Core Listings Domain](#core-listings-domain)
   - [Address & Spatial/Geographic Data](#address--spatialgeographic-data)
   - [Listing Attributes](#listing-attributes)
   - [ETL Pipeline Management](#etl-pipeline-management)
   - [Compliance & DNC](#compliance--dnc)
   - [System Lookups & Reference Tables](#system-lookups--reference-tables)
4. [Schema Analysis: `idx_config`](#4-schema-analysis-idx_config)
   - [MLS Number Validation](#mls-number-validation)
   - [Canonical Property Type Mapping](#canonical-property-type-mapping)
   - [School Type Normalization](#school-type-normalization)
   - [Cross-Schema Referential Integrity](#cross-schema-referential-integrity)
5. [Key Tables Reference](#5-key-tables-reference)
   - [Data Sources](#data-sources)
   - [Listings Core](#listings-core)
   - [Listing Attributes & Descriptions](#listing-attributes--descriptions)
   - [Property Classification](#property-classification)
   - [Geographic & School Data](#geographic--school-data)
   - [Brokers, Offices & Participants](#brokers-offices--participants)
   - [Listing Relationships](#listing-relationships)
6. [Non-Core & Utility Tables](#6-non-core--utility-tables)
   - [ETL Staging Tables](#etl-staging-tables)
   - [Temporary & Test Tables](#temporary--test-tables)
   - [Legacy Migration Tables](#legacy-migration-tables)
   - [Backup & Snapshot Tables](#backup--snapshot-tables)
   - [Benchmarking Tables](#benchmarking-tables)
   - [Maintenance & Cleanup Considerations](#maintenance--cleanup-considerations)
7. [Advanced Architecture & Technical Deep-Dives](#7-advanced-architecture--technical-deep-dives)
   - [Partitioning Deep-Dive](#partitioning-deep-dive)
   - [Storage & Row Design: Wide Tables](#storage--row-design-wide-tables)
   - [Referential Integrity & Application-Level Constraints](#referential-integrity--application-level-constraints)
   - [Multi-Source Data Model & Ingestion Workflow](#multi-source-data-model--ingestion-workflow)
8. [Relationship Model](#8-relationship-model)
9. [Recommended Engineering Guidelines & Future Roadmap](#9-recommended-engineering-guidelines--future-roadmap)
   - [Indexing Strategy](#indexing-strategy)
   - [Vacuuming & Maintenance for Wide Partitioned Tables](#vacuuming--maintenance-for-wide-partitioned-tables)
   - [Potential Schema Evolution](#potential-schema-evolution)
10. [Appendix: Methodology & Sources](#10-appendix-methodology--sources)

---

## 1. Executive Summary & System Purpose

This PostgreSQL database — referred to throughout this document as **HomelistingDB** — is the central data store for a real-estate listing and IDX (Internet Data Exchange) platform. It ingests, normalizes, stores, and serves MLS (Multiple Listing Service) listing data from dozens of independent data sources (e.g. ListHub, RMLS, CVRMLS, and other regional MLS boards) into a unified data model. The platform serves multiple downstream functions: consumer-facing property search, agent and office association, bonded listing alerts, compliance display rule enforcement, geocoding enrichment, and analytics-ready data for reporting and ad targeting.

The database spans **two schemas**:

- **`public`** — 161 tables and views, ~14,250 columns, 112 sequences, and over 630 indexes. This schema holds the entire application data model: listings, addresses, attributes, participants, offices, ETL pipeline state, compliance registries, geographic lookups, and various legacy/temporary/benchmarking tables.
- **`idx_config`** — 4 small configuration tables used exclusively during data ingestion to validate MLS numbers and map source-specific property type and school type codes to canonical internal values.

Across both schemas, only **4 database-level foreign-key constraints** exist — 2 within `public` and 2 cross-schema from `idx_config` to `public`. The vast majority of relational structure is maintained by application code and naming convention. This architectural decision, discussed in detail in Section 7, has significant implications for data integrity, ETL design, and maintenance operations.

---

## 2. Architectural Overview

### Multi-MLS Ingestion Pipeline

The platform receives listing data from multiple independent MLS boards, each with its own data format, field set, and update cadence. The `source` table (51 columns) serves as the master configuration record for each data source, controlling ingestion behavior, geocoding settings, photo-prefetch rules, and compliance display parameters. During ingestion, the ETL pipeline validates MLS numbers against per-source regular expressions (`idx_config.listing_mls_number_regex`), maps source-native property type codes to canonical classifications (`idx_config.listing_property_type`), and normalizes school type codes (`idx_config.listing_school_type`). Batch tracking, event logs, and error states are recorded in 11 `etl_*` tables providing full pipeline observability.

### Compliance & Display Rules

Real-estate data is subject to strict compliance requirements governing how listing information may be displayed to consumers. The `idx_display_rule` table stores per-source IDX compliance rules that the application layer consults before rendering listing data. The `dnc_registry` table maintains a Do-Not-Call phone number registry with per-jurisdiction boolean flags (federal and state-level), and an associated view (`dnc_registry_view`) exposes a computed `is_dnc` flag consulted before placing outbound calls or texts. These compliance mechanisms ensure the platform adheres to MLS board rules, fair display guidelines, and telecommunications regulations.

### Geocoding & Spatial Pipeline

Each listing's address flows through a geocoding enrichment pipeline. The `geocoding_lookup` table caches provider responses (keyed by address string and provider) to avoid redundant API calls. The `listing_address` table holds structured address components, while `listing_address_standard` extends this with USPS-normalized fields, FIPS codes, and geocoding metadata (76 columns). Geographic area hierarchies are managed through `area`, `source_area`, and `source_area_autocomplete_config` tables powering area-based search and autocomplete.

### Active Search vs. Historical Archive

The database architecture distinguishes between active inventory queries and historical archive access through its partitioning strategy. The core `listing` table is range-partitioned by `source_status` into `listing_p_active` (on-market), `listing_p_inactive` (withdrawn/expired), and `listing_p_sold` (closed). Consumer-facing search queries target only the `_p_active` partition, which is optimized with appropriate indexes for fast retrieval. Historical queries — for sold-price comparisons, market analytics, or compliance audit trails — access `_p_sold` or `_p_inactive` partitions, which carry their own index sets tuned for different access patterns. This separation ensures that the write-heavy ingestion workload and the read-heavy search workload do not contend on the same physical data pages.

---

## 3. Schema Analysis: `public`

### Core Listings Domain

The heart of the schema is the `listing` table (71 columns), which stores one row per MLS listing per data source. Each listing carries identifiers (`mls_number`, `source_id`), status references (`listing_status_id`, `listing_category_id`), property classification (`property_type_id`, `property_sub_type_id`), pricing, dates, and metadata. Satellite tables extend the listing with address data (`listing_address`, `listing_address_standard`), standardized and custom MLS attributes (`listing_attribute`, `listing_attribute_custom`), free-text descriptions (`listing_description`), marketing metadata (`listing_marketing_info`), school associations (`listing_school`, `listing_school_district`), and participant/office linkages (`listing_participant_rel`, `listing_real_estate_office_rel`). Lookup tables such as `listing_status` (12 columns), `listing_category` (5 columns), `listing_property_type` (6 columns), and `listing_property_sub_type` (6 columns) provide the canonical code lists that classify listings. The `listing_property_type_search` table (24 columns) denormalizes type and sub-type into a search-optimized form with boolean classification flags for faceted search.

A `listing_change` table captures listing mutations eligible to trigger inclusion in bonded listing alerts for persons bonded to those listings, while a `listing_score` table stores per-listing quality/preference scoring used to influence ranking and display eligibility in search results.

### Address & Spatial/Geographic Data

Geographic data is spread across 13 tables. The two per-listing address tables (`listing_address` at 34 columns, `listing_address_standard` at 76 columns) cover everything from raw street components to USPS-normalized forms and geocoded coordinates. The `area` and `source_area` tables define geographic area hierarchies used for area-based search (cities, neighborhoods, ZIP codes, custom regions), with `source_area_autocomplete_config` providing per-source configuration for search autocomplete behavior. The `geocoding_lookup` table caches provider responses to avoid redundant external API calls.

### Listing Attributes

The attribute subsystem uses two extremely wide tables — `listing_attribute` (1,596 columns) and `listing_attribute_custom` (1,584 columns) — that store one column per MLS attribute field and one row per listing. `listing_attribute` holds standardized fields (bedrooms, bathrooms, square footage, lot size, features, amenities), while `listing_attribute_custom` holds source-specific fields that have not been mapped to the standardized schema. The trade-offs of this wide-table design are discussed in Section 7.

### ETL Pipeline Management

Eleven `etl_*` tables track the full lifecycle of data ingestion: `etl_dataload` and `etl_status` record batch-level state, `etl_insert_listings` and `etl_update_listings` track per-listing insert/update operations, `etl_delete_listing` logs removals, `etl_error` captures processing failures, `etl_log` provides a general event log, `etl_batch_notification` and `etl_notification_messages` manage alerting, and `etl_time_dimension_monthly` supports time-based aggregation. An `etl_test_listings` table supports ingestion pipeline testing.

### Compliance & DNC

Beyond the `idx_display_rule` and `dnc_registry` tables described in Section 2, the compliance domain is relatively compact. The `dnc_registry` table (with its associated view) is the primary enforcement mechanism for Do-Not-Call regulations, with per-jurisdiction boolean columns enabling fine-grained compliance checks. The platform's compliance posture is predominantly application-driven, with the database serving as the lookup layer.

### System Lookups & Reference Tables

A collection of small lookup tables provides the standardized codes that normalize the heterogeneous data arriving from dozens of MLS sources. Key lookups include `listing_status`, `listing_category`, `listing_property_type`, `listing_property_sub_type`, `mls_board` (MLS board registry), and `broker` / `real_estate_office` / `real_estate_participant` for the brokerage ecosystem. These tables are typically seeded during onboarding of a new data source and updated infrequently.

---

## 4. Schema Analysis: `idx_config`

The `idx_config` schema is a small, focused configuration schema (4 tables) that the ETL pipeline consults during data ingestion. Unlike the `public` schema, it enforces referential integrity through foreign-key constraints.

### MLS Number Validation

The `listing_mls_number_regex` table stores one regular expression per data source (`source_id`). During ingestion, incoming MLS listing numbers are validated against the source's regex pattern to catch malformed or invalid identifiers before they enter the main data model. This prevents data quality issues from propagating into the `listing` table, where they would be significantly harder to detect and remediate.

### Canonical Property Type Mapping

The `listing_property_type` table (25 columns) is the most complex table in this schema. It maps each data source's native property type and sub-type codes to the platform's canonical `public.listing_property_type` and `public.listing_property_sub_type` lookups. Each row is uniquely identified by the combination (`source_id`, `property_type_id`, `property_sub_type_id`) and carries 16 boolean classification flags (`is_condo`, `is_single_family_home`, `is_land`, `is_rental`, `is_commercial_property`, etc.) that power the platform's faceted search filters. An `approval_date` column suggests a human review/approval workflow for new mappings.

### School Type Normalization

Two tables handle school type normalization: `listing_school_type` maps MLS-native school type strings to internal (`ylopo_school_type`) values, with an `active` flag allowing deprecated mappings to be soft-deleted. The `ylopo_school_type` table provides the canonical list of internal school type codes. Together, these ensure that school data from heterogeneous MLS sources is presented consistently to consumers.

### Cross-Schema Referential Integrity

The `idx_config.listing_property_type` table has two enforced foreign-key constraints referencing `public.listing_property_type(id)` and `public.listing_property_sub_type(id)`. These are the only cross-schema FK constraints in the database and ensure that every ingestion-time property classification maps to a valid canonical type. This is noteworthy because it means adding a new property type or sub-type requires coordinating inserts across both schemas — the canonical record must exist in `public` before the `idx_config` mapping row can reference it.

---

## 5. Key Tables Reference

### Data Sources

| Table | Columns | Description |
|---|---|---|
| `public.source` | 51 | An MLS/IDX data source and its per-source ingestion, geocoding, photo-prefetch, and compliance-display configuration (e.g. ListHub, RMLS, CVRMLS). Central reference for all source-specific behavior. |

### Listings Core

| Table | Columns | Description |
|---|---|---|
| `public.listing` | 71 | Core real-estate listing table: one row per MLS listing per source. Range-partitioned by `source_status` into child tables `listing_p_active`, `listing_p_inactive`, and `listing_p_sold`. The central entity of the database. |
| `public.listing_status` | 12 | Lookup table of standardized listing statuses (active, pending, sold, etc.), referenced by `listing.listing_status_id`. |
| `public.listing_category` | 5 | Lookup table of listing categories, referenced by `listing.listing_category_id`. |

### Listing Attributes & Descriptions

| Table | Columns | Description |
|---|---|---|
| `public.listing_attribute` | 1,596 | Wide attribute table storing one column per standardized MLS attribute field, one row per listing. Contains the bulk of property detail data (bedrooms, bathrooms, square footage, features, etc.). |
| `public.listing_attribute_custom` | 1,584 | Wide attribute table for source-specific (non-standardized) MLS fields, one row per listing. Structure mirrors `listing_attribute` but holds custom/vendor-specific fields. |
| `public.listing_description` | 9 | Listing description/remarks text, one row per listing. Stores the free-text property descriptions displayed to consumers. |
| `public.listing_marketing_info` | 15 | Marketing-specific listing metadata such as virtual tour URLs, branding, and display preferences. |

### Property Classification

| Table | Columns | Description |
|---|---|---|
| `public.listing_property_type` | 6 | Canonical lookup table of property types (residential, commercial, land, etc.). Referenced by listings and by `idx_config.listing_property_type` for ingestion-time mapping. |
| `public.listing_property_sub_type` | 6 | Canonical lookup table of property sub-types (single family, condo, townhouse, etc.). Referenced by listings and by `idx_config` for ingestion mapping. |
| `public.listing_property_type_search` | 24 | Search-optimized property type reference combining type, sub-type, and boolean classification flags (is_condo, is_land, is_rental, etc.) used to power faceted search. |
| `idx_config.listing_property_type` | 25 | Per-source property type/sub-type mapping table with boolean classification flags. Maps each source's native property type codes to the canonical `public.listing_property_type` and `public.listing_property_sub_type` lookups via enforced foreign keys. |

### Geographic & School Data

| Table | Columns | Description |
|---|---|---|
| `public.listing_address` | 34 | Structured address components for each listing (street, city, state, ZIP, county, coordinates). |
| `public.listing_address_standard` | 76 | Extended/standardized address representation with additional geocoding, FIPS, and USPS-normalized fields. |
| `public.listing_school` | 18 | Schools associated with a listing's location, typically linked by district or proximity. |
| `public.listing_school_district` | 11 | School district assignments for listings, used for school-based property search. |

### Brokers, Offices & Participants

| Table | Columns | Description |
|---|---|---|
| `public.real_estate_office` | 26 | Real-estate brokerage offices imported per data source. Stores office name, address, contact details, and source-specific identifiers. |
| `public.real_estate_participant` | 20 | MLS agents and brokers (participants) imported per data source, linked to listings via `listing_participant_rel`. Roughly one row per participant per source. |

### Listing Relationships

| Table | Columns | Description |
|---|---|---|
| `public.listing_participant_rel` | 10 | Junction table associating listings with participants (agents/brokers) and their roles (listing agent, buyer agent, co-listing agent, etc.). |
| `public.listing_real_estate_office_rel` | 9 | Junction table associating listings with brokerage offices and their roles (listing office, selling office, etc.). |

---

## 6. Non-Core & Utility Tables

Approximately 50 of the 161 tables in `public` are not part of the actively-maintained core data model. Understanding their role is important for capacity planning, maintenance operations, and schema cleanup.

### ETL Staging Tables

Eleven `etl_*` tables support the ingestion pipeline: batch tracking, per-listing operation logs, error capture, notification management, time-dimensional aggregation, and test fixtures. These tables accumulate data continuously and are candidates for periodic truncation or archival once their retention window passes.

### Temporary & Test Tables

Tables prefixed with `temp_` or `test_` (or suffixed `_test`) appear to be ad-hoc working tables created during development, debugging, or one-off data investigations. These typically mirror a subset of columns from core tables and may contain stale data.

### Legacy Migration Tables

Seven tables prefixed with `ctmp_` or `ctmp2_` are artifacts of a prior schema migration. Their naming suggests they were created as intermediate staging during a column restructuring or data backfill operation. They are likely safe to drop after confirming no active queries or scheduled jobs reference them.

### Backup & Snapshot Tables

Tables containing `_backup` or `_bck` in their names are point-in-time snapshots of core tables, created before destructive data operations. Their retention value diminishes as the data ages.

### Benchmarking Tables

Four `pgbench_*` tables (`pgbench_accounts`, `pgbench_branches`, `pgbench_history`, `pgbench_tellers`) are standard PostgreSQL pgbench artifacts used for performance benchmarking. They are unrelated to application data and can be removed from production environments.

### Maintenance & Cleanup Considerations

A cleanup strategy should: (1) audit non-core tables for remaining references in application code or scheduled jobs; (2) drop confirmed-unused tables; (3) establish naming conventions to prevent ad-hoc table proliferation; and (4) consider moving ETL tables into a dedicated `etl` schema.

---

## 7. Advanced Architecture & Technical Deep-Dives

### Partitioning Deep-Dive

The `listing` table is range-partitioned by `source_status` into three child tables:

- **`listing_p_active`** — currently active/on-market listings
- **`listing_p_inactive`** — withdrawn, expired, or off-market listings
- **`listing_p_sold`** — closed/sold listings

**Performance benefits:** Consumer-facing search queries overwhelmingly target active listings. By isolating active inventory in its own partition, the planner can perform partition pruning to eliminate `_p_inactive` and `_p_sold` from query plans entirely. This reduces I/O, improves index efficiency (smaller B-tree depth), and keeps the working set that must fit in `shared_buffers` much smaller than a single monolithic table.

**Indexing benefits:** Each partition can carry indexes tuned for its specific access patterns. `_p_active` may emphasize search-oriented indexes (by location, price range, property type), while `_p_sold` may carry indexes optimized for sold-price lookups and CMA (Comparative Market Analysis) queries. Index maintenance (reindex, bloat) is also faster on smaller partitions.

**Maintenance benefits:** `VACUUM` and `ANALYZE` operations can be targeted at the partition experiencing the most churn (typically `_p_active` during business hours). Partition-level operations — such as archiving old sold listings or rebuilding indexes — do not require locking or scanning the entire listing dataset.

### Storage & Row Design: Wide Tables

The `listing_attribute` (1,596 columns) and `listing_attribute_custom` (1,584 columns) tables represent an architectural decision to use a **one-column-per-field** design rather than an EAV (Entity-Attribute-Value) model.

**Advantages over EAV:** Queries against known attributes are fast and type-safe — a `WHERE bedrooms >= 3 AND bathrooms >= 2` filter is a direct index scan, not a self-join across an EAV triple store. Column-level statistics (`pg_statistic`) enable accurate cardinality estimates. Adding a new column via `ALTER TABLE ADD COLUMN` is a metadata-only operation in PostgreSQL (no table rewrite) when the column has no default or a volatile default.

**Trade-offs and PostgreSQL implications:** PostgreSQL has a hard limit of 1,600 columns per table (`MaxHeapAttributeNumber`), and `listing_attribute` at 1,596 columns is within 4 of that limit. Rows wider than ~2 KB are subject to TOAST compression and out-of-line storage, adding read overhead for full-row fetches. At ~1,600 columns the null bitmap alone is 200 bytes per row, and `pg_attribute` catalog bloat can slow DDL operations.

**Practical considerations:** Query patterns should select only needed columns (avoid `SELECT *`). If the platform approaches the column limit, the recommended path is a JSONB sidecar column or a dedicated overflow table.

### Referential Integrity & Application-Level Constraints

Only **4 database-level FK constraints** exist across both schemas:

- `public`: 2 constraints (specific tables identifiable in the full reference documentation)
- `idx_config`: 2 cross-schema constraints (`listing_property_type.property_type_id` → `public.listing_property_type.id`, `listing_property_type.property_sub_type_id` → `public.listing_property_sub_type.id`)

All other relationships — including critical ones like `listing.source_id` → `source.id` and `listing.listing_status_id` → `listing_status.id` — are enforced by **application code and naming convention only**.

**Implications for data integrity:** The database will not reject orphaned references. If a `source` row is deleted while `listing` rows still reference its `source_id`, those listings become orphans silently. Data integrity depends entirely on the application layer and ETL pipeline.

**Implications for data cleanup:** Without `ON DELETE CASCADE` or `SET NULL`, cleanup of parent records requires scanning all child tables that reference the parent via convention-named `*_id` columns. Periodic integrity audit queries (e.g., scanning for `listing.source_id` values absent from `source.id`) are advisable.

**Implications for indexing:** Without FK constraints, PostgreSQL does not auto-create indexes on referencing columns. The schema compensates with over 630 explicit indexes, but any new convention-based relationship must be accompanied by manual index creation to avoid full-table scans on joins.

### Multi-Source Data Model & Ingestion Workflow

Every core entity is scoped to a **data source** (`source_id`). A single physical property may appear as multiple rows in `listing` — one per MLS source that carries it. Similarly, `real_estate_participant` and `real_estate_office` are per-source, so the same agent or office may exist as multiple rows if they operate across MLS boards. The `listing_participant_rel` and `listing_real_estate_office_rel` junction tables associate each listing with its agent(s) and office(s) within the same source context.

**Handle-space isolation:** Each MLS source operates in its own identifier space. An MLS number like "12345" from RMLS is entirely unrelated to "12345" from CVRMLS. The combination of (`source_id`, `mls_number`) forms the logical unique identifier for a listing, preventing cross-source collisions without requiring globally unique identifiers.

**Deduplication considerations:** Cross-source deduplication — identifying that the same physical property appears under different MLS numbers in different sources — is not handled at the database level. The schema does not contain a canonical property entity or cross-source mapping table. Deduplication, if needed, must occur in the application or analytics layer, likely using address matching or geocoding proximity.

---

## 8. Relationship Model

The diagram below summarizes the primary relationships among the key tables. **Solid lines** represent enforced foreign-key constraints; **dashed lines** represent relationships documented in column naming or comments but not enforced by the database.

```
source (51 cols)
  :
  :..source_id...> listing (71 cols)
                     |
                     |--listing_id--> listing_address (34 cols)
                     |--listing_id--> listing_address_standard (76 cols)
                     |--listing_id--> listing_attribute (1,596 cols)
                     |--listing_id--> listing_attribute_custom (1,584 cols)
                     |--listing_id--> listing_description (9 cols)
                     |--listing_id--> listing_marketing_info (15 cols)
                     |--listing_id--> listing_school (18 cols)
                     |--listing_id--> listing_school_district (11 cols)
                     |--listing_id--> listing_participant_rel (10 cols)
                     |                   :..participant_id..> real_estate_participant
                     |--listing_id--> listing_real_estate_office_rel (9 cols)
                     |                   :..office_id..> real_estate_office
                     :
                     :..listing_status_id..> listing_status (12 cols)
                     :..listing_category_id.> listing_category (5 cols)
                     :..property_type_id...> listing_property_type (6 cols)
                     :..property_sub_type_id> listing_property_sub_type (6 cols)

idx_config.listing_property_type (25 cols)
  |---property_type_id----> public.listing_property_type [FK]
  |---property_sub_type_id-> public.listing_property_sub_type [FK]

Legend:  |--  = naming-convention relationship (unenforced)
         :..  = naming-convention relationship (unenforced)
         ---> [FK] = enforced foreign-key constraint
```

---

## 9. Recommended Engineering Guidelines & Future Roadmap

### Indexing Strategy

The database currently carries over 630 indexes across the `public` schema. While comprehensive indexing supports the platform's diverse query patterns, each index incurs write-time overhead (every `INSERT`, `UPDATE`, and `DELETE` must maintain all affected indexes) and storage cost. Recommendations:

- **Audit unused indexes** using `pg_stat_user_indexes.idx_scan` to identify indexes with zero scans. Drop unused indexes to reclaim storage and reduce write amplification.
- **Review duplicate/overlapping indexes.** Some tables may carry both a single-column index and a multi-column index with the same leading column — the single-column index is redundant.
- **Ensure covering indexes** on high-frequency search queries against `listing_p_active`, validated against actual query plans.
- **Partial indexes** (e.g. `WHERE source_status = 'active'`) can further reduce index size and improve cache hit rates.

### Vacuuming & Maintenance for Wide Partitioned Tables

Wide tables with 1,500+ columns present specific maintenance challenges:

- **Autovacuum tuning:** Lower `autovacuum_vacuum_scale_factor` and `autovacuum_analyze_scale_factor` on wide tables (`listing_attribute`, `listing_attribute_custom`) where each row update generates significant dead-tuple bloat.
- **TOAST table monitoring:** Wide rows are heavily TOAST-compressed. Monitor `pg_toast` sizes alongside heap sizes; TOAST tables require their own vacuuming.
- **Partition-targeted maintenance:** Run `VACUUM ANALYZE` on individual partitions rather than the parent table to reduce lock contention.
- **Index bloat monitoring:** With 630+ indexes, monitor for bloat via `pgstattuple` and use `REINDEX CONCURRENTLY` for indexes exceeding 30-40% bloat.

### Potential Schema Evolution

Based on the current schema's characteristics, several evolution paths are worth evaluating:

- **JSONB sidecar for attribute overflow:** As `listing_attribute` approaches the 1,600-column PostgreSQL limit, new attributes can be stored in a JSONB column (`extended_attributes jsonb`) with GIN indexing, avoiding the hard column limit while maintaining queryability.
- **Dedicated ETL schema:** Moving the 11 `etl_*` tables into a dedicated `etl` schema would improve schema organization, simplify permission management, and make it easier to apply distinct retention policies.
- **Non-core table cleanup:** Establishing a formal deprecation/archival process for `temp_*`, `test_*`, `ctmp_*`, and `*_backup` tables would reduce catalog bloat and improve schema introspection clarity.
- **Selective FK enforcement:** Adding foreign-key constraints on the most critical relationships (`listing.source_id` → `source.id`, `listing.listing_status_id` → `listing_status.id`) would provide a safety net against the most impactful orphan scenarios without requiring a full constraint retrofit. The performance cost of FK enforcement on these low-cardinality lookup joins is negligible.
- **Cross-source deduplication layer:** If the platform needs to present deduplicated property records to consumers (rather than per-source listings), a future `property` entity with a mapping table (`property_listing_rel`) would provide the canonical grouping without disrupting the existing per-source data model.

---

## 10. Appendix: Methodology & Sources

This document was generated from `information_schema` and `pg_catalog` metadata exports (`columns`, `table_constraints`, `key_column_usage`, `pg_indexes`, `pg_description`, `pg_sequences`). Descriptions marked *(inferred)* were derived from naming conventions and are not verified against application logic. All constraint, index, and column metadata is factual and taken directly from the database catalog. For complete per-table column listings, constraints, and index definitions, see the full reference documentation: `public-schema.md` and `idx_config-schema.md`.
