# Mushroom Cultivation Process Flowcharts (Mermaid)

## 1. Overall Process Flow (High-Level)

```mermaid
graph LR
    A["📦 Order Materials\n(materials table)"] --> B["🧪 Create Liquid Culture\n(liquid_cultures + inspections)"]
    A --> C["💧 Soaking Run\n(soakruns)"]
    A --> E["🍄 Bulk Spawn\n(bulks)"]

    B --> |ready| D["👜 Grain Spawn\n(spawnbags + inspections)"]
    C --> D

    D --> |fully colonized| F["🔀 Substrate Mixing\n(mixed_substrates)"]
    E --> |cooled ≤25°C| F

    F --> G["📦 Fruiting Blocks\n(fruiting_blocks + inspections)"]

    G --> |colonization complete| H["🌱 Fruiting\n(fruiting table)"]

    H --> |flush 1 & 2| I["🎯 Harvest\nEBIT/week calculation"]

    style A fill:#e1f5e1
    style I fill:#fff3cd
```

---

## QR Code Strategy (Manual vs App)

All processes that create trackable items (Liquid Cultures, Spawnbags, Fruiting Blocks, etc.) require unique QR code assignment. The approach differs by workflow:

### Manual Process (Current)
- **Step 1**: Create the record in database, generate unique ID
- **Step 2**: Manually record the ID on the physical QR code label (print or write)
- **Step 3**: Attach label to container
- **Database**: Store printed QR code string in table

### Smartphone App Process (Future)
- **Step 1**: Create the record in database, generate unique ID
- **Step 2**: Pre-printed QR codes exist (encoded with ID + table name as safety feature)
- **Step 3**: Worker scans the pre-printed QR code with phone
- **Database**: QR code automatically populated from scan (includes table context to prevent mislabeling)

**Safety Feature**: QR codes encode both the ID and the destination table (e.g., "SPAWNBAG:42" or "FBLOCK:128"), so scanning a wrong QR code type triggers a validation error.

---

## 2. Material Ordering Process (Two Stages)

### Stage 1: Order Placement & Recording

```mermaid
graph TD
    Start["Start: Material Needed"] --> Decision{Online or\nPhysical Store?}

    Decision -->|Online| Online["📝 Record:<br/>- Vendor URL<br/>- Order date<br/>- Quantity<br/>- Est. price incl. shipping"]
    Decision -->|Physical| Physical["📝 Record:<br/>- Vendor name<br/>- Item article #<br/>- Order date<br/>- Est. price"]

    Online --> Insert1["INSERT INTO materials (incomplete):<br/>material_type, vendor, order_date,<br/>amount_ordered, measuring_unit,<br/>order_link/article_number,<br/>price_total (estimated)<br/>❌ delivery_date = NULL (waiting)"]
    Physical --> Insert1

    Insert1 --> Waiting["⏳ WAITING: Order in Transit"]

    style Start fill:#e1f5e1
    style Waiting fill:#fff3cd
    style Insert1 fill:#ffe0b2
```

### Stage 2: Receiving & Verification

```mermaid
graph TD
    Receive["📦 Material Arrives"] --> Check["🔍 Check Delivery:"]

    Check --> Verify1["- Correct item?"]
    Check --> Verify2["- Correct quantity?"]
    Check --> Verify3["- Correct condition?"]
    Check --> Verify4["- Any damage/defects?"]

    Verify1 --> Decision{All Checks\nPassed?}
    Verify2 --> Decision
    Verify3 --> Decision
    Verify4 --> Decision

    Decision -->|Issues| Issues["⚠️ Document Issues:<br/>- Quantity mismatch<br/>- Damage<br/>- Wrong item<br/>- Record in comments"]

    Issues --> Update1["UPDATE materials:<br/>delivery_date = NOW(),<br/>comments += issue_notes<br/>amount_received (vs ordered)"]

    Decision -->|OK| Update2["✅ UPDATE materials:<br/>delivery_date = NOW(),<br/>amount_remaining = amount_ordered<br/>Mark as 'received'"]

    Update1 --> Store["Store in designated<br/>storage_location"]
    Update2 --> Store

    Store --> End["✅ Material in Inventory<br/>(ready for use in processes)"]

    style Receive fill:#e1f5e1
    style Decision fill:#fff3cd
    style End fill:#c8e6c9
    style Issues fill:#ffcdd2
```

---

## 3. Liquid Culture Creation Process

```mermaid
graph TD
    Start["Start: Create Liquid Culture<br/>(nutrient solution + species)"] --> Mix["Mix nutrient ingredients<br/>(malt, dextrose, gypsum, yeast, etc.)"]

    Mix --> Sterilize["Sterilize: 90 min @ 11 psi<br/>Pressure cooker"]

    Sterilize --> Cool["Cool to room temperature"]

    Cool --> Inoculate{Inoculation Source?}

    Inoculate -->|Existing LC| FromLC["Record:<br/>- fk_source_liquid_culture_id<br/>- fk_liquid_culture_id (this new culture)"]
    Inoculate -->|Spore Print| FromSpore["Record:<br/>- spore_print_source_location<br/>- species<br/>- fk_liquid_culture_id (this new culture)"]

    FromLC --> Insert["INSERT INTO liquid_cultures:<br/>datetime_inoculated,<br/>species, amount_ml,<br/>amount_remaining_ml,<br/>status = 'active'"]
    FromSpore --> Insert

    Insert --> Label["🏷️ Assign QR Code:<br/>(Manual: record ID manually<br/>App: scan QR code)<br/>Note: QR contains ID + table info"]

    Label --> Weekly["Weekly: Check growth progress"]

    Weekly --> Inspect["INSERT INTO lc_growth_inspections:<br/>colonization_%, appearance"]

    Inspect --> Check{Growth at 100?}

    Check -->|No, < Week 6| Weekly
    Check -->|No, >= Week 6| Discard1["UPDATE liquid_cultures:<br/>status = 'failed'<br/>DISCARD"]
    Check -->|Yes| Complete["UPDATE liquid_cultures:<br/>status = 'complete'<br/>datetime_ready_for_use = NOW()<br/>sterility_check_passed = ?"]

    Complete --> Fridge["Store in fridge (4°C)<br/>Viable for ~1 year<br/>amount_remaining = amount_ml"]

    Fridge --> Ready["Ready for spawnbag inoculation<br/>(10 mL per bag)"]

    Discard1 --> End1["❌ End: Failed Culture"]
    Ready --> End2["✅ End: LC Ready for Use"]

    style Start fill:#e1f5e1
    style End2 fill:#c8e6c9
    style End1 fill:#ffcdd2
    style Complete fill:#fff9c4
```

---

## 4. Soaking Process

```mermaid
graph TD
    Start["Start: Soak Grain<br/>(typically barley, 6 kg target)"] --> Measure["Measure dry grain weight<br/>Record in soakruns table"]

    Measure --> Insert1["INSERT INTO soakruns:<br/>datetime_started,<br/>fk_material_grain_id,<br/>weight_dry_grain"]

    Insert1 --> Fill["Fill container with water<br/>Set initial temperature"]

    Fill --> Record1["Record water_temp_initial"]

    Record1 --> Stir1["Stir grain immediately (2 min)<br/>Record datetime_stirs if tracked"]

    Stir1 --> Drain1["Drain water"]

    Drain1 --> Refill["Refill container, submerge grain<br/>Let soak ~24 hours"]

    Refill --> Monitor["Monitor during 24h:<br/>Optional: change water, stir<br/>Record all datetimes"]

    Monitor --> Update1["UPDATE soakruns:<br/>datetimes_water_changes,<br/>datetimes_stirs (comma-delimited)"]

    Update1 --> After24h["After 24 hours (20-30h acceptable)"]

    After24h --> Check1{Signs of<br/>Germination?}

    Check1 -->|Yes| Drain2["Drain water thoroughly<br/>Record datetime_finished"]
    Check1 -->|No| Boil["Optional: Hot-water cook step<br/>Heat to 70-90°C<br/>Cool, drain 20 min<br/>Record water_temp_max,<br/>boil_applied = TRUE"]

    Boil --> AddOpt["Optional: Add gypsum or other<br/>Record additives_applied"]

    AddOpt --> Drain2
    Drain2 --> MixOpt["If additives used:<br/>Mix thoroughly<br/>Record in additives_applied"]

    MixOpt --> FinalCheck{Germination signs<br/>observed?}

    FinalCheck -->|Yes| UpdateFinal["UPDATE soakruns:<br/>signs_of_germination = TRUE<br/>water_temp_final"]
    FinalCheck -->|No| UpdateFinal

    UpdateFinal --> End["✅ End: Soaked Grain Ready<br/>For Spawnbag Process"]

    style Start fill:#e1f5e1
    style End fill:#c8e6c9
    style Boil fill:#ffe0b2
    style Monitor fill:#bbdefb
```

---

## 5. Grain Spawn Process (Spawnbag Creation & Inoculation)

```mermaid
graph TD
    Start["Start: Create Spawn Bags<br/>From: Soakrun + Liquid Culture"] --> Fill["Fill spawnbags with soaked grain<br/>Target: 2.5 kg per bag"]

    Fill --> Weigh["Weigh filled bag"]

    Weigh --> Mark["Mark bag with binary pattern<br/>on filter pad corners:<br/>Bag 1: 0001, Bag 2: 0010, etc."]

    Mark --> Insert1["INSERT INTO spawnbags:<br/>datetime_created (now),<br/>fk_soakrun_id,<br/>weight_filled, bag_number,<br/>binary_marking_pattern"]

    Insert1 --> Batch["Batch bags for sterilization<br/>(2-3 at a time)"]

    Batch --> Sterilize["Sterilize in pressure cooker:<br/>90 min @ 11 psi<br/>Record: sterilization_duration_min,<br/>sterilization_psi"]

    Sterilize --> Cool["Cool SLOWLY:<br/>(stove off, lid on, no venting)<br/>Important for large bags!"]

    Cool --> UpdateSteril["UPDATE spawnbags:<br/>datetime_sterilized"]

    UpdateSteril --> Label["🏷️ Assign QR Code:<br/>(Manual: record unique ID manually<br/>App: scan printed QR code)<br/>Note: QR contains bag ID + table<br/>as safety feature"]

    Label --> Store["Sterilized bags can be stored<br/>indefinitely until inoculation"]

    Store --> Prep["Inoculation Prep:<br/>- Bring LC to room temp<br/>- Stir LC with magnetic stirrer<br/>- Wear nitrile gloves"]

    Prep --> Disinfect["Disinfect workspace + LC jar<br/>with isopropanol"]

    Disinfect --> Mount["Mount injection ports<br/>on spawnbags<br/>(spray ports with isopropanol first)"]

    Mount --> Steril["Heat sterilize syringe<br/>with blowtorch"]

    Steril --> Draw["Draw 10 mL LC into syringe"]

    Draw --> Inoculate["Inject into spawnbag<br/>via injection port"]

    Inoculate --> Insert2["INSERT INTO spawnbags:<br/>datetime_inoculated (NOW),<br/>fk_liquid_culture_id"]

    Insert2 --> Update_LC["UPDATE liquid_cultures:<br/>amount_remaining_ml -= 10"]

    Update_LC --> Store2["Move to inoculation storage<br/>(3+ weeks colonization)"]

    Store2 --> WeeklyCheck["Weekly: Inspect colonization"]

    WeeklyCheck --> Inspect["INSERT INTO spawnbag_inspections:<br/>colonization_%, moisture_level,<br/>contamination_visible, status"]

    Inspect --> Decision{Check Results}

    Decision -->|Contaminated| Discard["❌ DISCARD<br/>UPDATE spawnbag_inspections.status = 'contaminated'"]
    Decision -->|Contaminated| Discard["❌ DISCARD<br/>UPDATE spawnbag_inspections.status = ''"]
    Decision -->|Slow growth @8 weeks| Discard
    Decision -->|Progressing well| WeeklyCheck
    Decision -->|100% Colonized| Complete["✅ 100 Colonized<br/>spawnbag_inspections.status = 'complete'<br/>Ready for Substrate Mixing"]

    Discard --> End1["❌ End: Failed Spawnbag"]
    Complete --> End2["✅ End: Spawn Bag Ready"]

    style Start fill:#e1f5e1
    style End2 fill:#c8e6c9
    style End1 fill:#ffcdd2
    style Steril fill:#fff9c4
```

---

## 6. Bulk Spawn Process

**Note**: This is a **parallel, independent process**. Does NOT depend on Liquid Culture or Grain Spawn.
It runs in parallel and only combines with Grain Spawn during Substrate Mixing.

```mermaid
graph TD
    Start["Start: Create Bulk Substrate<br/>(Pasteurized growing medium)"] --> Measure["Measure components:"]

    Measure --> Coco["Coco coir (typically 650g)<br/>Record: fk_material_coco_coir_id,<br/>amount_coco_coir"]
    Coco --> Perlite["Perlite (typically 200g)<br/>Record: fk_material_perlite_id,<br/>amount_perlite"]
    Perlite --> Vermiculite["Vermiculite (typically 50g)<br/>Record: fk_material_vermiculite_id,<br/>amount_vermiculite"]
    Vermiculite --> Gypsum["Gypsum (typically 15g)<br/>Record: fk_material_gypsum_id,<br/>amount_gypsum"]

    Gypsum --> Pot["Put all components in pot"]

    Pot --> Water["Measure water (typically 3.5L)<br/>Record: water_volume"]

    Water --> Boil["Bring water to heavy boil"]

    Boil --> Pour["Pour boiling water into pot<br/>with substrate components"]

    Pour --> Cover["Cover with lid immediately<br/>Maintain heat for sterilization"]

    Cover --> Cool["Cool to ≤25°C<br/>(typically 12+ hours)<br/>Record: datetime_cooled_below_25c"]

    Cool --> Insert["INSERT INTO bulks:<br/>datetime_created,<br/>datetime_cooled_below_25c,<br/>all amounts,<br/>final_weight"]

    Insert --> Ready["✅ Ready for Substrate Mixing<br/>Must be used immediately<br/>(no shelf life)"]

    style Start fill:#e1f5e1
    style Ready fill:#c8e6c9
    style Cool fill:#bbdefb
```

---

## 7. Substrate Mixing Process (Create Fruiting Blocks)

**Note**: This process combines the outputs of TWO independent parallel processes:

- **Grain Spawn** (spawnbag fully colonized with LC)
- **Bulk Spawn** (substrate cooled to ≤25°C)

```mermaid
graph TD
    Start["Start: Mix Substrate<br/>Combining two parallel processes:<br/>1 Spawnbag (fully colonized) + 1 Bulk (cooled)"] --> GetSpawn["Get fully colonized spawnbag<br/>(from Grain Spawn process)"]

    GetSpawn --> GetBulk["Get cooled bulk substrate<br/>(from Bulk Spawn process)"]

    GetBulk --> Insert1["INSERT INTO mixed_substrates:<br/>datetime_mixed,<br/>fk_spawnbag_id,<br/>fk_bulk_id"]

    Insert1 --> PrepContainers["Prepare fruiting block containers:<br/>- Clean"]

    PrepContainers --> Wipe["- Wipe with isopropanol (50mL est.)<br/>Record: fk_material_container_id"]

    Wipe --> Holes["- Add breathing holes with filter patches<br/>(standardized, note any deviations)"]

    Holes --> Break["Break up spawnbag grain"]

    Break --> Mix["Mix grain + bulk substrate<br/>in container"]

    Mix --> LoopStart["For each block created:"]

    LoopStart --> Weight["Weigh filled container"]

    Weight --> Target["Compare to target weight<br/>(TBD from testing)"]

    Target --> Label["🏷️ Assign QR Code:<br/>(Manual: record unique ID manually<br/>App: scan printed QR code)<br/>Note: QR contains block ID + table"]

    Label --> Insert2["INSERT INTO fruiting_blocks:<br/>datetime_created,<br/>fk_mixed_substrate_id,<br/>qr_code, weight_at_creation,<br/>status = 'colonizing')"]

    Insert2 --> Count["Increment num_fruiting_blocks_created"]

    Count --> Update_MS["UPDATE mixed_substrates:<br/>num_fruiting_blocks_created"]

    Update_MS --> Store["Store in colonization area<br/>(room temp, proper stacking)"]

    Store --> WeeklyCheck["Weekly: Inspect colonization"]

    WeeklyCheck --> Inspect["INSERT INTO fruiting_block_inspections:<br/>colonization_%, moisture_level,<br/>contamination_visible"]

    Inspect --> Decision{Check Results}

    Decision -->|Contaminated| Discard["❌ DISCARD<br/>UPDATE fruiting_block.status = 'disposed'<br/>disposal_reason = 'contamination'"]
    Decision -->|Slow growth @8 weeks| Discard
    Decision -->|Progressing| WeeklyCheck
    Decision -->|100 Colonized| Complete["✅ Complete colonization<br/>UPDATE fruiting_block.status = 'ready_to_fruit'<br/>datetime_colonization_complete"]

    Discard --> End1["❌ End: Failed Block"]
    Complete --> End2["✅ End: Block Ready for Fruiting"]

    style Start fill:#e1f5e1
    style End2 fill:#c8e6c9
    style End1 fill:#ffcdd2
```

---

## 8. Fruiting Process (Harvest)

```mermaid
graph TD
    Start["Start: Fruiting<br/>Fully colonized blocks → Mushroom harvest"] --> Move["Move block to fruiting chamber<br/>(automatic climate control)"]

    Move --> Location["Record chamber location<br/>(Level, Zone, Grid reference)"]

    Location --> Insert1["INSERT INTO fruiting:<br/>datetime_moved_to_chamber,<br/>fk_fruiting_block_id,<br/>chamber_location,<br/>flush_number = 1"]

    Insert1 --> Monitor["Monitor in chamber<br/>(auto-conditions)<br/>Check every ~2 days"]

    Monitor --> PinCheck{First pins<br/>visible?}

    PinCheck -->|No, < 28 days| Monitor
    PinCheck -->|No, >= 28 days| Discard1["❌ DISCARD after 4 weeks<br/>UPDATE fruiting.datetime_disposed<br/>UPDATE fruiting_block.status = 'disposed'"]
    PinCheck -->|Yes| Wait["Wait for maturation<br/>~7-10 days to harvest"]

    Wait --> Harvest["Harvest mushrooms"]

    Harvest --> Weigh["Weigh fresh mushrooms"]

    Weigh --> Update1["UPDATE fruiting:<br/>datetime_flush_occurred,<br/>weight_harvested"]

    Update1 --> DecideFlush{Second Flush?<br/>Continue?}

    DecideFlush -->|No| Dispose1["UPDATE fruiting_block:<br/>status = 'disposed'<br/>Discard block"]
    DecideFlush -->|Yes, continue| Flush2["Wait for second flush<br/>(pins regenerate)"]

    Flush2 --> Monitor2["Monitor again<br/>(another ~7-10 days)"]

    Monitor2 --> Check2{Flush 2<br/>within 28 days?}

    Check2 -->|No| Discard2["❌ DISCARD after 4 weeks<br/>UPDATE fruiting.datetime_disposed"]
    Check2 -->|Yes| Harvest2["Harvest flush 2"]

    Harvest2 --> Weigh2["Weigh mushrooms"]

    Weigh2 --> Insert2["INSERT INTO fruiting<br/>flush_number = 2<br/>datetime_flush_occurred,<br/>weight_harvested"]

    Insert2 --> FinalDispose["UPDATE fruiting_block:<br/>status = 'disposed'<br/>Discard block<br/>(max 2 flushes)"]

    Dispose1 --> CalcEBIT["Calculate EBIT/week metrics"]
    FinalDispose --> CalcEBIT
    Discard1 --> CalcEBIT
    Discard2 --> CalcEBIT

    CalcEBIT --> Report["📊 Generate report:<br/>- Total grams harvested<br/>- Species performance<br/>- Failure rate %<br/>- Grams/week per LC species"]

    Report --> End["✅ End: Harvest Complete<br/>Data ready for CI analysis"]

    style Start fill:#e1f5e1
    style End fill:#c8e6c9
    style Report fill:#fff9c4
    style CalcEBIT fill:#fff9c4
```

---

## 9. Database & Process Integration Map

```mermaid
graph TB
    subgraph Materials["Materials Ordering"]
        MAT["materials table<br/>(vendor, price, storage)"]
    end

    subgraph LiquidCulture["Liquid Culture Creation"]
        LC["liquid_cultures<br/>(species, status, amount)"]
        LCI["lc_growth_inspections<br/>(weekly colonization %)"]
    end

    subgraph Soaking["Soaking Process"]
        SR["soakruns<br/>(temp, datetimes,<br/>germination)"]
    end

    subgraph SpawnBags["Grain Spawn"]
        SB["spawnbags<br/>(weight, qr_code,<br/>inoculation date)"]
        SBI["spawnbag_inspections<br/>(weekly: colonization,<br/>moisture, contamination)"]
    end

    subgraph BulkSpawn["Bulk Spawn<br/>PARALLEL PROCESS"]
        BU["bulks<br/>(components,<br/>amounts, datetime)"]
    end

    subgraph MixedSub["Substrate Mixing"]
        MS["mixed_substrates<br/>(1 bulk + 1 spawn<br/>→ n blocks)"]
    end

    subgraph FruitingBlocks["Fruiting Blocks"]
        FB["fruiting_blocks<br/>(colonization,<br/>status, weight)"]
        FBI["fruiting_block_inspections<br/>(weekly checks)"]
    end

    subgraph Fruiting["Fruiting & Harvest"]
        FT["fruiting<br/>(flush 1 & 2,<br/>weight harvested,<br/>chamber location)"]
    end

    MAT -->|grain| SR
    MAT -->|LC nutrients| LC
    MAT -->|spawnbag material| SB
    MAT -->|bulk components| BU
    MAT -->|containers| FB

    LC -->|ready| SB
    SR -->|soaked grain| SB

    SB -->|fully colonized| MS
    BU -->|cooled| MS

    MS -->|creates| FB

    FB -->|ready to fruit| FT
    LC -->|traceability| SB
    SB -->|traceability| MS

    SBI -->|monitors| SB
    LCI -->|monitors| LC
    FBI -->|monitors| FB

    FT -->|harvest data| End["🎯 EBIT/week Analysis<br/>Success rates by species<br/>Contamination rates by vendor<br/>Colonization time tracking"]

    style MAT fill:#e8f5e9
    style LC fill:#e3f2fd
    style SR fill:#fff3e0
    style SB fill:#fce4ec
    style BU fill:#f3e5f5
    style MS fill:#ffe0b2
    style FB fill:#c8e6c9
    style FT fill:#fff9c4
    style End fill:#ffe0b2
    style BulkSpawn stroke:#ff6b6b,stroke-width:3px,fill:#ffe0e0
```

---

## 10. Inspection & Auto-Discard Decision Tree

```mermaid
graph TD
    Inspect["🔍 Run Inspection<br/>(spawnbag or fruiting_block)"] --> GetAge["Get age from creation date<br/>days_elapsed = NOW - datetime_created"]

    GetAge --> CheckColonization["Check latest colonization_percent"]

    CheckColonization --> Decision1{Age >= 56 days?}

    Decision1 -->|No| Decision2{colonization<br/>== 100%?}
    Decision1 -->|Yes| CheckColony56["Has colonization_percent<br/>== 100% ever?"]

    CheckColony56 -->|Yes| Recent["✅ GOOD: Late colonizer<br/>May continue (edge case)"]
    CheckColony56 -->|No| FLAG["⚠️ FLAG FOR DISCARD<br/>Show to worker:<br/>'Bag/Block X needs discarding'"]

    Decision2 -->|Yes| FULL["✅ 100% Colonized<br/>Ready for next stage<br/>Update status field"]
    Decision2 -->|No| Monitoring["Continue monitoring<br/>Next inspection in 1 week"]

    Monitoring --> End1["Inspection complete"]
    FULL --> End2["Update status + dates"]
    Recent --> End3["Note in comments"]
    FLAG --> Notify["Worker notification:<br/>Item X ready for disposal"]
    Notify --> End4["Worker discards manually"]

    style Inspect fill:#e1f5e1
    style FLAG fill:#ffcdd2
    style FULL fill:#c8e6c9
    style Notify fill:#fff3cd
```

---

## Integration Checklist

✅ **All processes link to materials** → Every soakrun, bulk, spawnbag references material order IDs
✅ **Inspection tables track history** → spawnbag_inspections, fruiting_block_inspections, lc_growth_inspections
✅ **Auto-discard at 8 weeks** → Calculated at inspection time, flagged for worker
✅ **Traceability chain complete** → Harvest → Fruiting block → Mixed substrate → Spawn + Bulk → Materials
✅ **Comments column in all process tables** → Documents experiments & deviations
✅ **Picture paths for contamination** → Extensible for future smartphone app
✅ **EBIT/week metric** → Query: SUM(weight_harvested) / weeks for LC species, then cost-adjusted

---

## Next Steps

1. Create SQL schema (SQLite) from table definitions
2. Build CRUD endpoints (API layer for future smartphone app)
3. Create reporting dashboard queries (KPI tracking)
4. Implement inspection notification system (8-week auto-flag)
5. Plan photo storage strategy (local file system or cloud sync)
