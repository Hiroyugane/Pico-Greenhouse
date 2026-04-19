# Mushroom Cultivation Database Schema

**Version**: 1.0
**Last Updated**: 2026-04-18
**Purpose**: Centralized documentation for digital mushroom cultivation process tracking, failure analysis, and continuous improvement (EBIT per week in grams)

---

## Overview

This schema tracks 7 sequential cultivation processes with full traceability from material ordering through final fruiting. The design emphasizes:

- **Normalization**: Separate tables for processes (spawnbags, bulks) and their inspections (history tracking)
- **Traceability**: Every process links back to input materials and prior processes
- **Flexibility**: Comments column in all process tables for deviations/experiments
- **Extensibility**: Picture paths for contamination documentation; designed for future smartphone app integration

---

## Universal Table Columns

**All process/inspection tables include**:
- `id`: Primary key (auto-increment integer)
- `datetime_created` / `datetime_started`: When the process began
- `comments`: Text field for deviations, experiments, notes (e.g., "tested new breathing hole design", "unusual color on day 3")
- `picture_path`: Optional file path/URL for contamination/issue photos (future app integration)

---

## Table Definitions

### 1. **materials**

Core inventory of all input materials used across processes.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique material order |
| material_type | ENUM | NOT NULL | Values: `spawn_grain`, `spawnbags`, `injection_port`, `injection_tool`, `liquid_culture`, `coco_coir`, `vermiculite`, `perlite`, `gypsum`, `malt_extract`, `yeast`, `dextrose`, `isopropanol`, `nitrile_gloves` |
| vendor | VARCHAR(255) | NOT NULL | Supplier name |
| order_date | DATE | NOT NULL | When ordered |
| delivery_date | DATE | Nullable | When received; NULL during Stage 1 (Ordering), populated in Stage 2 (Receiving) |
| measuring_unit | ENUM | NOT NULL | Values: `kg`, `g`, `ml`, `each`, `block` |
| amount_ordered | DECIMAL(10,3) | NOT NULL | Quantity ordered |
| amount_used | DECIMAL(10,3) | DEFAULT 0 | Cumulative amount consumed |
| amount_remaining | DECIMAL(10,3) | GENERATED | = amount_ordered - amount_used |
| order_link | VARCHAR(500) | Optional | URL for online orders |
| price_total | DECIMAL(8,2) | NOT NULL | Total cost incl. shipping |
| storage_location | ENUM | NOT NULL | Values: `fridge`, `shelf_dry`, `drawer`, `freezer` |
| expiry_date | DATE | Optional | For reference; dry goods ~1yr from delivery |
| comments | TEXT | Optional | Batch notes, quality observations |

**Design Notes**:
- **Two-stage workflow**: Stage 1 (Ordering): Create record with `delivery_date = NULL`. Stage 2 (Receiving): Verify delivery and populate `delivery_date`, update `amount_remaining` only after verification
- `amount_remaining` is calculated to track available inventory
- `storage_location` supports future testing of optimal conditions
- No batch number field yet; will be added once batch-level failure correlation is needed
- Vendor quality rating can be computed from associated process failures post-analysis

---

### 2. **soakruns**

Grain soaking process (typically barley). One soakrun produces n spawnbags.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique soak batch |
| datetime_started | DATETIME | NOT NULL | When grain put in water |
| datetime_finished | DATETIME | NOT NULL | When water drained (20-30h after start) |
| fk_material_grain_id | INT | FK → materials | Links to spawn_grain order |
| weight_dry_grain | DECIMAL(8,3) | NOT NULL | Pre-soak weight (kg) |
| water_temp_initial | DECIMAL(5,2) | NOT NULL | Starting water temp (°C) |
| water_temp_max | DECIMAL(5,2) | NOT NULL | Highest reached (when heat off) |
| water_temp_final | DECIMAL(5,2) | NOT NULL | Temp after cooling/before bagging (°C) |
| datetimes_water_changes | TEXT | Optional | Comma-delimited ISO timestamps (e.g., "2026-04-18T14:30, 2026-04-19T09:15") |
| datetimes_stirs | TEXT | Optional | Comma-delimited ISO timestamps of manual mixing |
| boil_applied | BOOLEAN | DEFAULT FALSE | Whether hot-water cooking step used |
| additives_applied | TEXT | Optional | E.g., "gypsum 15g" (comma-delimited) |
| signs_of_germination | BOOLEAN | DEFAULT FALSE | Observed sprouting/moisture absorption |
| comments | TEXT | Optional | E.g., "grain appeared dry after 24h", "tested cold-soak variant" |
| picture_path | VARCHAR(500) | Optional | Photo of grain state at completion |

**Design Notes**:
- All timestamps in ISO-8601 format (YYYY-MM-DD HH:MM:SS)
- Comma-delimited datetimes chosen for simplicity (not normalized further to reduce tables)
- Weight variance (absorption rate) calculated post-analysis: `(final_weight - dry_weight) / dry_weight`
- Boil/additives optional flags support experimentation
- Soakruns themselves cannot fail; status is determined when bagged

---

### 3. **spawnbags**

Grain spawn bags created from a soakrun. Filled, sterilized, then inoculated separately.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique spawn bag |
| datetime_created | DATETIME | NOT NULL | When bagged (end of soakrun) |
| datetime_sterilized | DATETIME | NOT NULL | When sterilization completed |
| datetime_inoculated | DATETIME | Optional | When LC injected (starts 8-week timer) |
| fk_soakrun_id | INT | FK → soakruns | Source soakrun |
| fk_material_spawnbag_id | INT | FK → materials | Links to spawnbag material order |
| fk_material_injection_port_id | INT | FK → materials | Links to injection port order |
| fk_liquid_culture_id | INT | FK → liquid_cultures | Which LC used for inoculation |
| weight_filled | DECIMAL(8,3) | NOT NULL | Weight when filled (kg) |
| bag_number | INT | NOT NULL | Sequential number (1-16 per batch) |
| binary_marking_pattern | VARCHAR(4) | NOT NULL | Binary dots on filter (e.g., "1011" for bags 11) |
| qr_code | VARCHAR(255) | NOT NULL UNIQUE | Printed identifier |
| sterilization_duration_min | INT | NOT NULL | Minutes @ pressure (typically 90) |
| sterilization_psi | INT | NOT NULL | Pressure (typically 11 psi) |
| cooling_method | ENUM | NOT NULL | Values: `slow_passive` (stove off, lid on) |
| comments | TEXT | Optional | "Slow cooling achieved in 8h", "steam vented unevenly" |
| picture_path | VARCHAR(500) | Optional | Photo at inoculation or issue |

**Design Notes**:
- `datetime_created` ≠ `datetime_sterilized` to support pre-sterilization storage
- `datetime_inoculated` nullable because sterilized bags can be stored before inoculation
- Binary marking uses bits 1-4 for 16 bags max (user confirmed never > 16)
- Sterilization parameters fixed by convention (90 min, 11 psi) but stored for audit
- No `status` field; health tracked separately in `spawnbag_inspections`

---

### 4. **spawnbag_inspections**

Weekly health checks of spawn bags (one record per inspection). Tracks colonization, moisture, contamination history.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique inspection record |
| fk_spawnbag_id | INT | FK → spawnbags | Which bag inspected |
| datetime_checked | DATETIME | NOT NULL | When inspection occurred |
| days_since_inoculation | INT | COMPUTED | = days(datetime_checked - spawnbag.datetime_inoculated) |
| colonization_percent | INT | Range 0–100 | % of grain showing mycelium (0-100) |
| moisture_level | ENUM | NOT NULL | Values: `dry`, `good`, `wet` |
| contamination_visible | BOOLEAN | DEFAULT FALSE | Green/blue/other mold observed |
| contamination_type | VARCHAR(100) | Optional | If contaminated: describe color/pattern |
| status | ENUM | NOT NULL | Values: `healthy`, `contaminated`, `slow_growth`, `complete` |
| comments | TEXT | Optional | E.g., "white mycelium at bag corners", "liquid pooling at base" |
| picture_path | VARCHAR(500) | Optional | Photo of contamination or growth |

**Design Notes**:
- One record per week (or per check)
- `days_since_inoculation` supports calculations (e.g., "is this bag slow at day 35?")
- Auto-discard flag: if `days_since_inoculation >= 56` (8 weeks) AND `colonization_percent < 100`, worker is notified at next inspection
- Contamination documented with type/photo for root-cause analysis
- Full history preserved; queries can show progression over time

---

### 5. **bulks**

Bulk substrate prepared via sterilization (coco coir + perlite + vermiculite + gypsum + water). One bulk can supply 1–3 spawnbags.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique bulk batch |
| datetime_created | DATETIME | NOT NULL | When water poured, heating started |
| datetime_cooled_below_25c | DATETIME | NOT NULL | When temp dropped to ≤25°C |
| fk_material_coco_coir_id | INT | FK → materials | Coco coir component |
| amount_coco_coir | DECIMAL(8,3) | NOT NULL | kg used |
| fk_material_vermiculite_id | INT | FK → materials | Vermiculite component |
| amount_vermiculite | DECIMAL(8,3) | NOT NULL | kg used |
| fk_material_perlite_id | INT | FK → materials | Perlite component |
| amount_perlite | DECIMAL(8,3) | NOT NULL | kg used |
| fk_material_gypsum_id | INT | FK → materials | Gypsum component |
| amount_gypsum | DECIMAL(8,3) | NOT NULL | kg used |
| water_volume | DECIMAL(8,3) | NOT NULL | Liters (e.g., 3.5) |
| final_weight | DECIMAL(8,3) | NOT NULL | Total weight after cooling (kg) |
| comments | TEXT | Optional | E.g., "coco coir appeared dry", "water boil time extended 5 min" |

**Design Notes**:
- Bulk is **always used immediately** after cooling; no shelf-life
- Separate columns per material type for traceability (failures can be linked to material batch)
- No `status` field; bulk is either being prepared, ready, or consumed
- No shelf-life enforced; process ensures immediate mixing

---

### 6. **mixed_substrates**

Result of combining one spawnbag + one bulk → multiple fruiting blocks. One record per spawbag+bulk pairing.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique mixing batch |
| datetime_mixed | DATETIME | NOT NULL | When spawnbag & bulk combined |
| fk_spawnbag_id | INT | FK → spawnbags | Fully colonized spawnbag |
| fk_bulk_id | INT | FK → bulks | Source bulk substrate |
| fk_material_container_id | INT | FK → materials | Fruiting block container type/order |
| num_fruiting_blocks_created | INT | NOT NULL | How many blocks filled from this mix (typically 1–3) |
| comments | TEXT | Optional | E.g., "bulk appeared drier than expected", "tested new container size" |
| picture_path | VARCHAR(500) | Optional | Photo of mixing or block setup |

**Design Notes**:
- One bulk + one spawnbag → n fruiting blocks (1:many relationship to fruiting_blocks)
- `fk_material_container_id` links to the container material order (for cost tracking)
- No separate materials tracking for prep (isopropanol, gloves); estimated at 50 mL iso + gloves per process
- Records the *creation* of fruiting blocks; block colonization tracked in `fruiting_blocks` & `fruiting_block_inspections`

---

### 7. **fruiting_blocks**

Physical blocks created from mixed_substrates. One record per filled container in colonization/fruiting stage.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique fruiting block |
| datetime_created | DATETIME | NOT NULL | When filled/mixed |
| datetime_colonization_complete | DATETIME | Optional | When substrate fully white |
| fk_mixed_substrate_id | INT | FK → mixed_substrates | Lineage back to spawn + bulk |
| qr_code | VARCHAR(255) | NOT NULL UNIQUE | Printed identifier |
| weight_at_creation | DECIMAL(8,3) | NOT NULL | kg at fill |
| target_weight | DECIMAL(8,3) | Optional | Ideal weight for yield (TBD from testing) |
| status | ENUM | NOT NULL | Values: `colonizing`, `ready_to_fruit`, `fruiting`, `disposed` |
| disposal_reason | VARCHAR(255) | Optional | E.g., "contamination detected week 2", "did not colonize in 8 weeks" |
| comments | TEXT | Optional | "Very compact fill", "visible contamination on day 10" |
| picture_path | VARCHAR(500) | Optional | Photo of colonization or contamination |

**Design Notes**:
- Represents one filled container (2L typical capacity)
- Status transitions: `colonizing` → `ready_to_fruit` → `fruiting` → `disposed`
- Auto-dispose flag: if `status = colonizing` AND `days_since_created >= 56`, worker notified at inspection
- One block can generate 2 flushes (tracked separately in `fruiting` table)

---

### 8. **fruiting_block_inspections**

Weekly health checks of colonizing/fruiting blocks. Similar structure to spawnbag_inspections.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique inspection record |
| fk_fruiting_block_id | INT | FK → fruiting_blocks | Which block inspected |
| datetime_checked | DATETIME | NOT NULL | When inspection occurred |
| days_since_creation | INT | COMPUTED | = days(datetime_checked - fruiting_block.datetime_created) |
| colonization_percent | INT | Range 0–100 | % of substrate showing white mycelium |
| moisture_level | ENUM | NOT NULL | Values: `dry`, `good`, `wet` |
| contamination_visible | BOOLEAN | DEFAULT FALSE | Green/blue/other mold observed |
| contamination_type | VARCHAR(100) | Optional | If contaminated: describe |
| status | ENUM | NOT NULL | Values: `colonizing`, `contaminated`, `slow_growth`, `ready_to_fruit` |
| comments | TEXT | Optional | E.g., "primordia visible on surface", "liquid pooling" |
| picture_path | VARCHAR(500) | Optional | Photo of contamination or growth |

**Design Notes**:
- Same structure as spawnbag_inspections for consistency
- Auto-discard: if `status = colonizing` AND `days_since_creation >= 56` AND `colonization_percent < 100`
- Once `colonization_percent = 100` & no contamination, `fruiting_block.status` → `ready_to_fruit` and `datetime_colonization_complete` set

---

### 9. **fruiting**

Actual harvest events. One block generates up to 2 flushes.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique harvest record |
| datetime_moved_to_chamber | DATETIME | NOT NULL | When block moved to fruiting chamber |
| fk_fruiting_block_id | INT | FK → fruiting_blocks | Which block |
| chamber_location | VARCHAR(50) | NOT NULL | E.g., "Level2-Left-Front" or grid reference |
| flush_number | INT | NOT NULL | 1 or 2 (after 2nd flush, block disposed) |
| datetime_flush_occurred | DATETIME | NOT NULL | When harvest happened |
| weight_harvested | DECIMAL(8,3) | NOT NULL | kg of fresh mushrooms |
| comments | TEXT | Optional | "First pins visible day 7", "unusually small fruiting bodies" |
| picture_path | VARCHAR(500) | Optional | Photo of harvest or yield |

**Design Notes**:
- One block → max 2 records (flush 1 & 2)
- `datetime_moved_to_chamber` is when fruiting begins; flushes typically 1 week apart
- Auto-dispose: if `flush_number = 2` recorded, fruiting_block marked as `disposed`
- Auto-flag: if `datetime_flush_occurred - datetime_moved_to_chamber > 28 days`, item flagged for disposal (4-week limit per flush)

---

### 10. **liquid_cultures**

Nutrient jars inoculated with species + growth tracking.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique liquid culture batch |
| datetime_inoculated | DATETIME | NOT NULL | When LC injected with species |
| species | VARCHAR(255) | NOT NULL | Mushroom species name (e.g., "Oyster", "Shiitake") |
| fk_source_liquid_culture_id | INT | FK → liquid_cultures | If inoculated from existing LC (else NULL) |
| fk_source_spore_print_id | INT | Optional | Future: link to spore prints table (if inoculated from print) |
| spore_print_source_location | VARCHAR(255) | Optional | Where spore print originated (e.g., "Supplier X batch 2025-11") |
| amount_ml | DECIMAL(8,2) | NOT NULL | Total volume (ml) |
| amount_remaining_ml | DECIMAL(8,2) | NOT NULL | Currently available for inoculation |
| storage_location | VARCHAR(100) | NOT NULL | Always "fridge" (stored at 4°C) |
| datetime_ready_for_use | DATETIME | Optional | When first 100% colonization detected |
| status | ENUM | NOT NULL | Values: `active`, `complete`, `failed`, `discarded` |
| sterility_check_passed | BOOLEAN | DEFAULT FALSE | Visual/smell verification before use |
| comments | TEXT | Optional | "Unusual smell detected day 3", "inoculated from batch X-2026" |
| picture_path | VARCHAR(500) | Optional | Photo if contamination suspected |

**Design Notes**:
- Inoculation volume: 10 mL per spawnbag
- Fridge storage extends viability to ~1 year
- `amount_remaining_ml` tracks how much is left for inoculations
- Auto-discard: if `status = active` AND `weeks_since_inoculation >= 6` AND `colonization_percent < 100`
- `sterility_check_passed` required before use (manual verification by worker)
- No deletion; all records kept for traceability & failure analysis

---

### 11. **lc_growth_inspections**

Weekly monitoring of LC growth (inoculation %).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | INT | PK, auto-increment | Unique inspection record |
| fk_liquid_culture_id | INT | FK → liquid_cultures | Which LC monitored |
| datetime_checked | DATETIME | NOT NULL | When observation made |
| days_since_inoculation | INT | COMPUTED | = days(datetime_checked - lc.datetime_inoculated) |
| colonization_percent | INT | Range 0–100 | Visual estimate of mycelium growth |
| appearance | VARCHAR(255) | Optional | E.g., "White haze forming", "Dense white strands visible" |
| comments | TEXT | Optional | "Magnetic stir running smoothly", "color appears off" |

**Design Notes**:
- One inspection per week (roughly)
- Progression tracked: 0% → 25% → 50% → 100%
- Auto-ready: when `colonization_percent = 100`, LC marked complete & `datetime_ready_for_use` set
- Auto-discard: at week 6, if `colonization_percent < 100`, worker notified

---

## Relationship Diagram

```
materials ──┐
            ├──→ soakruns ──→ spawnbags ──┐
            │                    ↓         │
            │          spawnbag_inspections
            │
            ├──→ bulks ────────────────────┤
            │                              │
            ├──→ liquid_cultures ──→────────┤
            │        ↓                      │
            │  lc_growth_inspections       │
            │                              ↓
            └─────────────────────→ mixed_substrates ──→ fruiting_blocks
                                                              ↓
                                                    fruiting_block_inspections
                                                              ↓
                                                            fruiting
```

---

## Key Traceability Examples

### Example 1: Trace a contaminated spawnbag to root cause
```sql
-- Find all spawnbags contaminated in past 7 days linked to specific barley supplier
SELECT sb.id, sb.qr_code, sb.datetime_inoculated, sbi.contamination_type,
       m.vendor, m.order_date, sr.datetimes_water_changes
FROM spawnbag_inspections sbi
JOIN spawnbags sb ON sbi.fk_spawnbag_id = sb.id
JOIN soakruns sr ON sb.fk_soakrun_id = sr.id
JOIN materials m ON sr.fk_material_grain_id = m.id
WHERE sbi.contamination_visible = TRUE
  AND sbi.datetime_checked >= DATE_SUB(NOW(), INTERVAL 7 DAY)
  AND m.vendor = 'Barley Supplier X';
```

### Example 2: Calculate EBIT per week for a liquid culture species
```sql
-- Total yield (g) per LC species in past 4 weeks / weeks elapsed
SELECT lc.species,
       SUM(f.weight_harvested * 1000) AS total_grams,
       (SUM(f.weight_harvested * 1000) / 4) AS grams_per_week,
       COUNT(DISTINCT f.fk_fruiting_block_id) AS blocks_harvested
FROM fruiting f
JOIN fruiting_blocks fb ON f.fk_fruiting_block_id = fb.id
JOIN mixed_substrates ms ON fb.fk_mixed_substrate_id = ms.id
JOIN spawnbags sb ON ms.fk_spawnbag_id = sb.id
JOIN liquid_cultures lc ON sb.fk_liquid_culture_id = lc.id
WHERE f.datetime_flush_occurred >= DATE_SUB(NOW(), INTERVAL 4 WEEK)
GROUP BY lc.species
ORDER BY grams_per_week DESC;
```

### Example 3: Find blocks ready for discard (8 weeks without full colonization)
```sql
-- Identify fruiting blocks stuck in colonization
SELECT fb.id, fb.qr_code, fb.datetime_created,
       DATEDIFF(NOW(), fb.datetime_created) AS days_elapsed,
       fbi.colonization_percent
FROM fruiting_blocks fb
LEFT JOIN fruiting_block_inspections fbi ON fb.id = fbi.fk_fruiting_block_id
WHERE fb.status = 'colonizing'
  AND DATEDIFF(NOW(), fb.datetime_created) >= 56
  AND (fbi.colonization_percent IS NULL OR fbi.colonization_percent < 100)
ORDER BY fb.datetime_created;
```

---

## Implementation Notes

- **Picturestorage**: Use relative paths (e.g., `photos/fruiting_block_123_contamination.jpg`) stored in application directory for local sqlite database (future smartphone app can extend with cloud sync)
- **Timestamps**: Always ISO-8601 format (YYYY-MM-DD HH:MM:SS) for cross-system compatibility
- **Enums**: Represented as CHECK constraints or separate lookup tables depending on SQLite version/ORM
- **Indexes**: Recommend on `fk_*` columns and `datetime_*` for fast range queries
- **Backups**: Weekly exports of CSV for failure analysis in spreadsheets
