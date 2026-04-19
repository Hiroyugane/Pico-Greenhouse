# Processes creation prompt

I want to document the manual mushroom cultivation processes with mermaid. I will describe you the process, and I want you to implement it in mermaid. Please also report if you find missing information or mismatching data, or you find optimization potential while reviewing.
Background info: the processes will be used to digitalize parts of the manual process, mainly the scientific/qualified documentation works for the continuos improvement and error search with failed/contaminated attempts. the digitalization will use a sqlite database for all data.

There will be the following processes:

1. Ordering Materials
2. Creating Liquid Culture
3. Spawn soaking
4. Creating Spawn
5. Creating Bulk
6. Substrate Mixing
7. Fruiting

## Database Tables

### materials

- ID
- Material Type (examples following)
  - spawn Grain
  - Spawnbags
  - Injectionport
  - Injectiontool
  - liquidculture (first generation purchased cultures only)
  - coco coir
  - vermiculite
  - perlite
  - gypsum
  - malt extract
  - yeast
  - dextrose
  - isopropanol
  - nitril gloves
- Vendor
- Order date
- amount measuring unit
- amount ordered
- amount used
- amount remaining
- order link
- price

### soakruns

- id
- datetime production start
- datetime production end
- datetimes stirs (array)
- datetimes freshwater-flushes (array)
- temperature boil (null if no boil occured)

### spawnbags

- id
- datetime production start
- datetime production end
- fk: id soaking process
- fk: id materials (spawnbags, injection port)

### bulks

- id
- material id coco coir
- material id gypsum
- material id vermiculite
- material id perlite
- amount coco coir
- amount id gypsum
- amount id vermiculite
- amount id perlite
- datetime

### mixed substrates

- id
- datetime
- id spawnbag
- id bulks
- (to do)

### liquid cultures

- id
- datetime inoculation
- species
- id original liquid culture
- is fully inoculated yes/no

### fruiting

- id
- datetime start
- datetime first flush
- datetime second flush/end
- location
- weight
- produce first flush
- produce second flush
- id mixed substrate

## The processes in detail

### Ordering Materials

materials can be bought either in an actual store, but mostly it's online shops. if its in physical stores, the article number should be recorded. in an online shop, the shop url should be recorded. in any case, the vendor, order date, and quantity ordered should be documented. if there is batch data available, this should also be recorded. in physical stores, the delivery date is the same as the order date. in physical stores, the delivery needs to be documented once it arrived successfully. a vendor review / documentation/database table might also be good, to document if specific products from a vendor is not usable for the processes or the quality is too bad, the shipping was bad, hidden costs etc. all materials used in further processes need to be ordered through the ordering materials process.

### Creating Liquid Culture

Liquid culture (with specimens) will be created by first by creating sterilized nutrient solution jars. they could contain a handful of ingredients, like malt, dextrose, honey, yeast, gypsum, etc., aswell as a magnetic stir bar. after the glasses got mixed, they will be sterilized in a pot at 90minutes@11psi. after sterilization and cooling down, The nutrient solution will be inoculated with a pre-existing liquid culture or spore print. if it's a pre-existing culture, the ID of the LQ should be documented. for spore prints, the species and the spore harvest date needs to be documented. the inoculation date of the nutrient solution needs to be documented also, and the unique id qr code will be attached to the jar. after inoculation, the liquid culture will be stirred weekly to support good growth. the progress will be reviewed by the worker on a weekly basis. the inoculation can be on a scale from 0-100. if the lc is not getting much progress or is not finished by week 6, it will be written off as failed and will be discarded. when it reaches 100 percent, it will be put in the fridge for cool storage and can be used for inoculation of grain spawn.

### Soaking

First, the grain to be soaked (usually barley) will be taken from the material storage and measured - right now, the goal is to use 6kg of dry barley per batch/process run, but this is not always the case. the exact weight is measured and documented, afterwards it is put in a big container. the container is then filled with water - varying in temperature for testing what works best. this can be cold water, warm water (~50°C) or hot water (~70°C). the mix is then stirred directly afterwards (maybe 2 minutes later so the heat can be absorbed by the grain) and then the water poured off. then the water will be filled again so the grain is submerged well and can be mixed well. The mixture should then soak for about 24 hours. inbetween, irregularly, the water can be changed or the mixture could be stirred, depending on the time available to the worker. after 24 hours, the grain should be just barely starting to germinate - depending on the vendor / batch of grain, this is not always the case, but should be documented if it is the case. Then, the soak finish datetime will then be recorded and water will be poured off as much as possible. then comes an optional cooking step to hydrate the grain further, if needed (for example if no germination happened). the grain will be transferred to a pot and filled with water again. the mixture will then be brought to a high temperatur (usually 70-90°C), then taken off the stove and poured off the water again (temperature should be documented). in either case, the grain should wait about 20 minutes for the water to drain / the grain to dry a little. lastly, optionally there can be added some additional materials, for example gypsum. when adding more materials, these should be documented with their quantity, then mixed afterwards. The result is a container filled with soaked and hydrated, optionally additives and ready for the next process: grain spawn.

### Grain Spawn

after soaking, the grain spawn process is about packing the individual spawn bags, sterilizing and inoculating them.
As a requirement, the process needs the soaked grain, liquid culture, injection tools (syringe), some isopropanol, a blowtorch, lighter, injection ports, grow bags. first, the soaked grain needs to be put in spawnbags. for this, a growbag will be put on a scale and filled until a certain weight - right now, the weight is betwenn 1kg and 3kg. the specfic weight per bag will be documented. the bags will also be marked in order of filling, to determine which got filled first and which got filled last (the last ones will have more water, probably). For this, dots will be placed on the protruding corners of the inserted filter pad - in a binary system, going from: top left, top right, bottom left, bottom right (bits 1,2,3,4). Meaning Bag 1 will have one dot on the top left, bag 2 on top right, bag 3 will have both top dots etc. - after the bags got filled and the weight documented, they will be sterilized in a pressure cooking pot - two or three at a time. the bags will be brought to temperature (11psi) and left for sterilizing for 90 minutes, then very slowly cooled down. after all the bags have been sterilized, the bags get their actual unique Identified code, stuck on them as a qr-code. the ids are printed in advance and will need to be saved in the database for the respective bag. now we have multiple spawn bags, cooled down, identified and ready for inoculation. this also means that for a soak process, usually about 5-7 spawn bags will be created.
in the meantime, the liquid culture needs to be brought to room temperature and be mixed with the magnetic stirrer. afterwards, the worker needs to wear nitrile gloves. then, the injection ports can be sprayed down with isopropanol and stuck to the growbags. then, the whole work area needs to be desinfected with isopropanol, including the liquid culture glass jar. if the workspace is prepared, the blowtorch will be activated and the syringe sterilized. then, liquid culture is being sucked with the syringe and the bags inoculated with it. After inoculation, it needs to be documented which spawn bag id got inoculated with which liquid culture id. Then, the spawnbags will be brought into the inoculation storage for at least 3 weeks, with checks about every week. When checking, the worker needs to review the state of the grain - it can be that no inoculation is visible, or inoculation from 0-100 percent. the review can also determine that the bag is contaminated. besides the growth status, the humidity of the grain is also important. if it's too wet, too dry, or good humidity. if the bag is contaminated, it will be written of and disposed of. if it takes longer than 8 weeks for full inoculation, it will also be marked as too weak and will be disposed of. this all needs to be documented, aswell as the date when the bag was checked. if this should be in the grainspawn table or a separate table is undecided yet.

### bulk spawn

For bulk spawn, X amount of coco coir (usually one 650g block) will be put in a pot, aswell as X amount of perlite (200g) and X amount of vermiculite (50g), aswell as some gypsum (15g). then, X amount of water will be brought to boiling (3,5L default). When the water is boiling heavily, it will be poured into the prepared pot with the materials and then covered with a lid. the mixture will then be covered to keep the temperature high and will be left to cool for about 12 hours. after it is cooled, the bulk is ready to be used.

### Substrate mixing

this process is about creating the fruiting blocks for the production. After the bulk substrate is created and ready, a fully inoculated spawnbag will be broken up and mixed with the bulk substrate with datetime documentation. It should be noted that the bulk substrate will be enough for 1-3 spawnbags, but the spawnbags will not be mixed together because they could be different mushroom species. This means, that one bulk spawn batch can create multiple substrate mixing batches. Anyway, before mixing, the fruiting block containers need to be prepared. they are plastic boxes that will be filled with the substrate mix. They need to be cleaned, wiped with isopropanol and prepared with breathing holes with filterpatches. Once that is done, the substrate can be mixed and then be poured in the containers. They can hold about 2 Litres. They will also get unique identifier qr-codes and the weight will be documented once their are filled. There will be a target weight to prevent overfilling/overcompressing, but this target weight is not known yet. Once they are filled, they will get their qr code attached and then be brought to the storage to fully colonize the substrate - about 2-4 weeks. the same way as in the grain spawn process, the fruiting substrate blocks will be checked weekly for moisture, colonization status and contamination. If there is contamination, they will be written off and disposed of, aswell as if they take longer than 8 weeks for colonization. If they colonized completely, they will be brought to the fruiting process.

### Fruiting

For fruiting, the fully colonized bulkspawn substrate blocks will be brought in the fruiting chamber and documented when this happens. the chamber is automatic, so there is not much to do. there only needs to be documented the allocated space where the block is in the fruiting chamber (levels 1,2,3,4, left, right, front, back, middle, in a 3x3 grid). there will be two flushes per fruiting block. then, it will be documented when the flush happens and how much fresh material is harvested per flush. if a flush takes longer than 4 weeks, the block will be written off as failed and disposed of. after the second flush, it will also be disposed of.
