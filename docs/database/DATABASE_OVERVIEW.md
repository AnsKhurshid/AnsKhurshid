# PostgreSQL Database Overview

## Table of Contents

- [Executive Summary](#executive-summary)
- [Schema Overview](#schema-overview)
  - [public Schema](#public-schema)
  - [idx_config Schema](#idx_config-schema)
- [Key Tables](#key-tables)
  - [Data Sources](#data-sources)
  - [Listings Core](#listings-core)
  - [Listing Attributes & Descriptions](#listing-attributes--descriptions)
  - [Property Classification](#property-classification)
  - [Geographic & School Data](#geographic--school-data)
  - [Brokers, Offices & Participants](#brokers-offices--participants)
  - [Listing Relationships](#listing-relationships)
- [Data Architecture Highlights](#data-architecture-highlights)
- [Relationship Model](#relationship-model)

---

## Executive Summary

This PostgreSQL database powers a **real-estate listing and IDX (Internet Data Exchange) platform**. Its primary function is to ingest, normalize, store, and serve MLS (Multiple Listing Service) listing data from multiple data sources (e.g. ListHub, RMLS, CVRMLS) into a unified data model that supports property search, agent/office association, compliance display rules, and downstream consumer-facing products.

The database spans **two schemas** — `public` (161 tables/views) and `idx_config` (4 tables) — containing approximately 14,250 columns, 4 foreign-key constraints, and 124 sequences. The `public` schema holds the full application data model, while `idx_config` holds small configuration lookup tables used during data ingestion. Of the 161 tables in `public`, roughly 85 are core listing-related tables; the remainder support ETL operations, geographic lookups, compliance, and legacy/temporary workloads.

---

## Schema Overview

### public Schema

The `public` schema is the primary application schema, organized around a central **listing** entity with satellite tables for addresses, attributes, descriptions, marketing data, schools, and property classification. Supporting entities include **data sources** (`source`), **brokers and offices** (`real_estate_office`, `real_estate_participant`), **geographic areas** (`area`, `source_area`, `geocoding_lookup`), and **compliance** (`dnc_registry`, `idx_display_rule`).

Tables follow a consistent naming convention: most listing-related tables share a `listing_` prefix and join back to the core `listing` table via a `listing_id` column, though these relationships are enforced by application code rather than database-level foreign keys. Several tables follow a partition-like naming pattern — `listing_p_active`, `listing_p_inactive`, `listing_p_sold` — indicating range-partitioning by listing status, confirmed by the `listing` table's own `pg_description` comment. Lookup/reference tables such as `listing_status`, `listing_category`, `listing_property_type`, and `listing_property_sub_type` provide the standardized code lists that classify listings for search and display.

The ETL pipeline is served by a dedicated set of tables (`etl_listing_batch`, `etl_listing_batch_raw`, `etl_listing_batch_event`, and others) that track ingestion runs, raw payloads, processing events, and error states. A `listing_change` table captures listing mutations eligible for inclusion in bonded listing alerts. Compliance is handled through `dnc_registry` (Do-Not-Call phone number registry with per-jurisdiction flags) and `idx_display_rule` (IDX compliance display rules governing how listing data can be shown to consumers). Geographic support comes from `area`, `source_area`, `geocoding_lookup`, and related tables that store area hierarchies, autocomplete configurations, and cached geocoding provider responses.

The schema also contains a substantial number of **non-core tables** (~50) used for ETL staging (`etl_*`), temporary/test workloads (`temp_*`, `test_*`), legacy migration (`ctmp_*`, `ctmp2_*`), backup snapshots (`*_backup`, `*_bck`), and PostgreSQL benchmarking (`pgbench_*`). These are documented but grouped separately from the active data model.

### idx_config Schema

The `idx_config` schema holds **4 small lookup/configuration tables** used to validate and normalize incoming MLS listing data during ingestion. Its tables define:

- Regular expressions for validating MLS numbers per data source (`listing_mls_number_regex`).
- Standardized property type and sub-type mappings from source-specific codes to internal classification flags (`listing_property_type`).
- School type code mappings between MLS-native and internal values (`listing_school_type`, `ylopo_school_type`).

Unlike the `public` schema, `idx_config` does enforce referential integrity: `listing_property_type` has two cross-schema foreign keys referencing `public.listing_property_type(id)` and `public.listing_property_sub_type(id)`, tying ingestion-time property classification back to the canonical lookup tables.

---

## Key Tables

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

## Data Architecture Highlights

### Partitioning Strategy

The `listing` table is range-partitioned by `source_status` into three child tables:

- **`listing_p_active`** — currently active/on-market listings
- **`listing_p_inactive`** — withdrawn, expired, or off-market listings
- **`listing_p_sold`** — closed/sold listings

This partitioning enables efficient queries that target only active inventory (the most common access pattern) without scanning the full historical dataset.

### Wide Attribute Tables

The `listing_attribute` (1,596 columns) and `listing_attribute_custom` (1,584 columns) tables use a **one-column-per-field** design rather than an EAV (entity-attribute-value) model. This is a deliberate trade-off: it makes queries against known attributes fast and type-safe, at the cost of very wide rows and schema changes when new MLS fields are introduced.

### Convention-Based Referential Integrity

Only **4 foreign-key constraints** exist across both schemas (2 in `public`, 2 cross-schema in `idx_config`). The vast majority of relationships — such as `listing.source_id` referencing `source.id`, or `listing.listing_status_id` referencing `listing_status.id` — are enforced by **application code and naming convention only**. This means:

- Column names like `*_id` reliably indicate a relationship to the table matching the prefix (e.g. `listing_status_id` → `listing_status.id`).
- The database will **not** reject orphaned references or cascade deletes for most relationships.
- Data integrity depends on the application layer and ETL pipeline, not database constraints.

### Multi-Source Data Model

Every core entity is scoped to a **data source** (`source_id`). A single physical property may appear as multiple rows in `listing` — one per MLS source that carries it. Similarly, `real_estate_participant` and `real_estate_office` are per-source, so the same agent may exist as multiple rows if they operate across MLS boards. This design supports federated ingestion from dozens of independent MLS systems without requiring cross-source deduplication at the database level.

---

## Relationship Model

The diagram below summarizes the primary relationships among the key tables. **Solid lines** represent enforced foreign-key constraints; **dashed lines** represent relationships that are documented in column naming or comments but not enforced by the database.

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

*Document generated from `information_schema` and `pg_catalog` metadata exports. Descriptions without a database comment were inferred from naming conventions. See the full reference documentation (`public-schema.md`, `idx_config-schema.md`) for complete column, index, and constraint details.*
