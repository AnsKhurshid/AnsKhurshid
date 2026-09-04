# PostgreSQL Database Documentation

This directory documents the two schemas present in this PostgreSQL database, generated from a metadata
export (`information_schema`/`pg_catalog`-derived table, column, constraint, index, and comment data).

## Schemas

| Schema | Purpose | Tables/Views | Docs |
|---|---|---|---|
| `public` | Primary application database for a real-estate listing / IDX platform: MLS listing ingestion, normalization, search support, brokers/offices/participants, compliance (DNC, IDX display rules), ETL pipeline tracking, and related product areas. | 161 | [public-schema.md](./public-schema.md) |
| `idx_config` | Small lookup/configuration tables used to validate and normalize incoming MLS data during ingestion (MLS number regex validation, property-type and school-type code lists). | 4 | [idx_config-schema.md](./idx_config-schema.md) |

## How this documentation was produced

- Source: a JSON metadata export containing, per table, its type, comment, columns (name, data type,
  nullable, default, comment), constraints (primary key, unique, foreign keys, checks), and indexes
  (name and full `CREATE INDEX` definition), plus a list of sequences.
- **Factual content** (table/column names, types, nullability, defaults, constraints, indexes, and any
  comment text) is taken directly from the metadata without alteration.
- **Descriptions** are used verbatim from database comments where present. Where no comment exists, a
  concise description was **inferred** from the table/column name and is explicitly marked *(inferred)*
  in the tables below — these are best-effort guesses, not verified facts.
- **Relationships**: the metadata contains 4 declared `FOREIGN KEY` constraints across both schemas
  (2 in `public`, 2 cross-schema in `idx_config`). Several additional relationships are documented only in column comments (e.g.
  `listing.source_id` → `source.id`); these are shown in each schema's ER diagram as dotted,
  **unenforced** edges, clearly distinguished from the 4 constraint-enforced (solid) edges. No
  relationship is asserted in this documentation beyond what is stated in a constraint or a comment.
- Tables are grouped into categories (e.g. "Core Listing Data", "Temporary, Test, Backup & Scratch
  Tables") based on naming conventions, to make the large `public` schema (161 tables) navigable. This
  grouping is organizational only and does not imply schema-level namespacing.

## Notable characteristics of this database

- **Referential integrity is largely convention-based, not enforced.** Only 4 foreign-key constraints exist across both schemas (2 in `public`, 2 cross-schema in `idx_config`). Of the 161 tables in `public`, only 2
  have a `FOREIGN KEY` constraint. The `idx_config.listing_property_type` table references two `public`-schema lookup tables. Most relational structure (e.g. `listing_status_id` →
  `listing_status.id`) relies on application code and naming convention rather than the database
  guaranteeing consistency. Treat any relationship not listed as "Enforced: Yes" in a schema doc as
  informational only.
- **No explicit partitioning metadata was present** in the export (no `PARTITION OF` / inheritance
  information). Several tables follow a `<name>_p_active` / `<name>_p_inactive` / `<name>_p_sold` or
  `<name>_inactive` naming pattern that strongly suggests partitioning or a status-based table split
  (e.g. `listing` / `listing_p_active` / `listing_p_inactive` / `listing_p_sold`); this is called out as
  an inferred note on the relevant tables, not asserted as confirmed partitioning.
- **A large portion of the schema is not part of the actively-maintained data model**: temporary
  (`temp_*`), test (`test_*`/`*_test`), backup (`*backup*`/`*_bck*`), legacy migration (`ctmp_*`/`ctmp2_*`),
  and `pgbench_*` benchmarking tables make up a significant share of the 161 tables in `public`. These are
  grouped into their own sections in [public-schema.md](./public-schema.md) so the core, actively-used
  entities (listing, broker, real_estate_office, real_estate_participant, source, mls_board, area, etc.)
  are easy to find.
- **`listing_attribute*` and `direct_crmls_listing` are extremely wide tables** (500–1,596 columns each),
  storing one column per standardized or source-specific MLS attribute. Their full column lists are
  included in the docs for completeness but are long by nature of the source data model, not a
  documentation artifact.
