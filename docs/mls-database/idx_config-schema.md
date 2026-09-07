# idx_config Schema — IDX Configuration

The `idx_config` schema stores **IDX-specific configuration rules** that control how MLS data is classified, normalized, and displayed. It handles property type classification, school type normalization, and MLS number formatting.

---

## Schema Summary

| Metric | Value |
|--------|-------|
| Tables | 3 |
| Sequences | 1 |
| Foreign Keys | 0 |
| Table Comments | 0 |

---

## Table of Contents

1. [listing_property_type](#1-listing_property_type)
2. [listing_school_type](#2-listing_school_type)
3. [listing_mls_number_regex](#3-listing_mls_number_regex)

---

## Tables

### 1. listing_property_type

Maps MLS-specific property type/sub-type combinations to standardized boolean classification flags. Each MLS source defines its own property type taxonomy, and this table normalizes them into a consistent set of boolean categories.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | | Primary key |
| `source_id` | integer | NO | | MLS source identifier |
| `property_type_id` | integer | NO | | Source property type ID |
| `property_type` | text | YES | | Source property type label |
| `property_sub_type_id` | integer | NO | | Source property sub-type ID |
| `property_sub_type` | text | YES | | Source property sub-type label |
| `is_condo` | boolean | YES | | Condominium |
| `is_foreclosure` | boolean | YES | | Foreclosure |
| `is_land` | boolean | YES | | Vacant land |
| `is_manufactured_home` | boolean | YES | | Manufactured home |
| `is_mobile_home` | boolean | YES | | Mobile home |
| `is_multifamily` | boolean | YES | | Multi-family |
| `is_rental` | boolean | YES | | Rental property |
| `is_short_sale` | boolean | YES | | Short sale |
| `is_single_family_home` | boolean | YES | | Single-family home |
| `is_townhouse` | boolean | YES | | Townhouse |
| `is_income_property` | boolean | YES | | Income property |
| `is_commercial_property` | boolean | YES | | Commercial property |
| `is_farm_ranch` | boolean | YES | | Farm/ranch |
| `is_other` | boolean | YES | | Other/uncategorized |
| `is_coop` | boolean | YES | | Cooperative |
| `is_condop` | boolean | YES | | Condop |
| `is_condo_hotel` | boolean | YES | | Condo hotel |
| `y_creation_date` | timestamptz | NO | | Internal creation timestamp |
| `y_last_update_date` | timestamptz | NO | | Internal last-update timestamp |
| `approval_date` | timestamptz | YES | | Approval timestamp |

**Primary Key:** `id`
**Unique Index:** `source_id, property_type_id, property_sub_type_id` (compound unique)
**Indexes:**
- `listing_property_type_pkey` (btree on `id`)
- `listing_property_type_id_idx` (btree on `property_type_id`)
- `listing_property_type_property_sub_type_idx` (btree on `property_sub_type`)
- `listing_property_type_property_type_idx` (btree on `property_type`)
- `listing_property_type_source_id_idx` (btree on `source_id`)
- `listing_property_type_source_id_property_type_id_property_s_idx` (unique, compound)

---

### 2. listing_school_type

Normalizes MLS-specific school type labels to Ylopo-standard school types.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | *sequence* | Auto-increment surrogate key |
| `mls_school_type` | text | NO | | Original MLS school type label |
| `ylopo_school_type` | text | YES | | Normalized Ylopo school type |
| `active` | boolean | YES | `true` | Whether mapping is active |
| `y_creation_date` | timestamptz | NO | `now()` | Internal creation timestamp |
| `y_last_update_date` | timestamptz | NO | `now()` | Internal last-update timestamp |
| `approval_date` | timestamptz | YES | | Approval timestamp |

**Primary Key:** `id`
**Indexes:** `listing_school_type_pkey` (btree on `id`)
**Estimated Rows:** ~101

---

### 3. listing_mls_number_regex

Defines regular expressions for normalizing MLS listing numbers per source. Strips prefixes, suffixes, or reformats MLS numbers to a standard format.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | integer | NO | | Primary key |
| `source_id` | integer | YES | | MLS source identifier |
| `expression` | text | YES | | Regex pattern to match |
| `expression_replace_with` | text | YES | | Replacement pattern |

**Primary Key:** `id`
**Indexes:** `listing_mls_number_regex_pkey` (btree on `id`)

---

## Sequences

| Sequence | Owned By | Last Value |
|----------|----------|------------|
| `listing_school_type_id_seq` | `listing_school_type.id` | 101 |

---

## Design Patterns

### Boolean Classification Matrix
`listing_property_type` uses a **wide boolean flag** approach to classify properties. A single MLS property type/sub-type combination can map to multiple boolean categories simultaneously (e.g., a property could be both `is_condo` and `is_income_property`). This denormalized design optimizes search queries by avoiding joins.

### Approval Workflow
Both `listing_property_type` and `listing_school_type` include an `approval_date` column, suggesting a review/approval workflow for configuration changes before they take effect.

### Regex-Based Normalization
`listing_mls_number_regex` allows per-source regex transformations on MLS numbers, supporting both extraction (`expression`) and replacement (`expression_replace_with`) patterns.
