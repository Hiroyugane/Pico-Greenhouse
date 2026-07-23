# Firmware build & freeze runbook

> How to build, flash, and version-verify a custom Pi Greenhouse firmware
> offline, and how to adopt a newer MicroPython without stranding the field
> units. Punch item **P7** of
> [`firmware-freeze-versioning-plan.md`](../notes/firmware-freeze-versioning-plan.md);
> that document holds the *why*, this one holds the *how*.

**Read this first, in one sentence:** a frozen module can only be changed by
rebuilding and reflashing the firmware — the SD-payload updater cannot touch
it — so every step below is arranged around not needing a field trip to undo a
mistake.

---

## 0. Before you build anything: the measurement gate (P0.5)

Do not build a frozen firmware to "see if it helps". The council attached a
measurement rider to the freeze decision, because freezing permanently costs
OTA reach and two cheaper variants might already be enough.

> **Measured 2026-07-23 — this gate has been run and the answer was FREEZE.**
> A could not be deployed (the raw set no longer fits flash), B ran at 97.5 %
> heap use (~6 KB free), C was not relevant. Neither OTA-preserving variant is
> viable. Kept below as the procedure to repeat after any change that moves the
> heap; results live in [`hw-test-log.md`](../test/hw-test-log.md) FW.2.

Measure three variants, each a multi-hour bench soak with
`diagnostics.mem_trend_log = True` in `config.py`:

| # | Variant | How to produce it | OTA reach |
|---|---|---|---|
| **A** | Baseline | ship as today (raw `.py`) | full |
| **B** | `.mpy`-only | `build-mpy` task, then `build_update_payload.py --compiled` | **full** |
| **C** | Feature-stripped firmware | stock module set, unused MicroPython features disabled in the board config, **nothing frozen** | **full** |

Pull each run's `system.log` off the SD card, then:

```bash
python tools/heap_baseline.py A=logs/a-system.log B=logs/b-system.log C=logs/c-system.log --target-free 60000
```

- **A variant that keeps full OTA reach meets the target → stop. Do not
  freeze.** Ship that variant.
- **Nothing meets it →** proceed below, freezing the *coldest* modules first
  (`-FreezeOnly`) and re-measuring, rather than taking the whole tier at once.

Record the three figures and the verdict in
[`hw-test-log.md`](../test/hw-test-log.md).

---

## 1. One-time toolchain setup

**Build under WSL, not native Windows.** The RP2 port needs host-side tools
from the pico-SDK (`pioasm`, `picotool`) that want a Unix-ish C toolchain;
under WSL that is three apt packages, on native Windows it is an afternoon.
This machine's build path is **WSL2 / Ubuntu 24.04**.

```bash
wsl --install -d Ubuntu          # only if no distribution exists yet
```

```bash
sudo apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build \
    gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib \
    pkg-config libusb-1.0-0-dev
```

`pico-sdk`, `tinyusb`, `mbedtls`, and `picotool` are **not** installed by hand
— the build script fetches them as MicroPython submodules on first run.

Both builders check every tool before doing anything and list all the missing
ones at once. A build that fails preflight has changed nothing.

| Builder | Use when |
|---|---|
| [`tools/build_firmware.sh`](../../tools/build_firmware.sh) | **the normal path** — run inside WSL |
| [`tools/build_firmware.ps1`](../../tools/build_firmware.ps1) | native-Windows path, kept for a machine with a full MSYS2/Arm toolchain |

They implement the same steps and set the same manifest environment contract; a
test asserts they stay in agreement.

The MicroPython tree is **not vendored into this repo**. The shell builder
clones it to `$HOME/micropython` **inside the Linux filesystem** on purpose:
building on a 9p-mounted NTFS path (`/mnt/l/...`) is roughly an order of
magnitude slower. Override with `--mpy-dir`.

---

## 2. Build

```bash
wsl -d Ubuntu -- bash /mnt/<drive>/<path-to-repo>/tools/build_firmware.sh
```

or `run fwbuild`. What happens, and what to watch:

1. **Preflight** — toolchain check (above).
2. **Ref resolution** — the pinned MicroPython ref comes from
   [`tools/micropython.lock`](../../tools/micropython.lock). It is committed,
   so the second and every later build is reproducible. `-Repin` re-resolves
   the newest **final** upstream release and rewrites the lock; pre-releases
   (`-rc`, `-preview`) are never selected, and "latest master" is never an
   option.
3. **Checkout + submodules** into the sibling tree.
4. **`mpy-cross` built from that same tree.** This is the load-bearing step —
   see §5.
5. **`fw_info.py` generated** into `build/frozen/`, carrying
   `FIRMWARE_VERSION`, `MPY_ABI` (read out of the tree's `py/mpconfig.h`, never
   typed by hand), `MPY_SOURCE` (`upstream@tag@commit`), and `FROZEN_AT`.
6. **`make -C ports/rp2 BOARD=RPI_PICO FROZEN_MANIFEST=tools/freeze_manifest.py`**.
7. **Artifacts** — `build/firmware.uf2`, a version-stamped copy
   `build/firmware-<FIRMWARE_VERSION>.uf2`, and `build/firmware-build.json`
   recording the ref, ABI, freeze scope, and mpy-cross path. `build/` is
   gitignored.
8. **Freeze verification** — [`tools/verify_frozen_uf2.py`](../../tools/verify_frozen_uf2.py)
   reassembles the UF2 blocks into the flash image and checks that every module
   the manifest names is present, that `fw_info` and the expected
   `FIRMWARE_VERSION` are in there, and that **no** forbidden decision module
   leaked in. A non-zero exit fails the build.

   > **Why this step exists.** A build can succeed and still be *stock*: if
   > `FROZEN_MANIFEST` never reaches the port, or `PG_REPO_DIR` points
   > somewhere unexpected, `make` produces a perfectly good firmware with
   > nothing frozen. Every symptom is then a runtime one — modules still
   > import (from the filesystem), nothing crashes, and the only clue is a
   > `mem_trend` number that did not move after a flash-and-soak cycle. Run it
   > by hand against any image whose provenance you are unsure of:
   >
   > ```bash
   > python tools/verify_frozen_uf2.py build/firmware.uf2 --compare-stock build/rollback/RPI_PICO-20260406-v1.28.0.uf2
   > ```

### Controlling the freeze scope

| Flag | Effect |
|---|---|
| *(none)* | Tier-1 only: vendored drivers, device drivers, `boot_log`, `i2c_guard`, `sensor_paths`, `buzzer` |
| `-FreezeOnly 'sdcard.py,ds3231.py'` | just those — the P0.5 "coldest first, re-measure" loop |
| `-FreezeTier2` | adds the stable plumbing set. **Blocked until the next-rev migration closes** (plan §2.2) |

`co2_logger.py` is excluded from every scope on purpose: its sensing half is
stable, but it still carries the binary hysteresis override that the 0-100 CO₂
ramp will replace, and freezing the module freezes that decision too.

---

## 3. Flash

**Two things must be true before the `.uf2` is written.** Neither can be
recovered after the fact.

1. **The device has logged its current version.** Boot it on the *old*
   firmware and confirm `/boot.log` (or `system.log`) carries the
   `[VERSION] fw=… app=… mpy_abi=…` line. Once the new image is flashed, that
   line is the only record of what it was running.
2. **The previous `build/firmware-<version>.uf2` still exists.** BOOTSEL +
   drag-drop of that file is the *only* rollback for a bad frozen build.

Then: hold BOOTSEL while plugging in the Pico, and copy `build/firmware.uf2`
onto the mass-storage volume that appears. (`mpremote` works too, but BOOTSEL
is the path that also works when the firmware is too broken to talk.)

Re-flash the application afterwards — a firmware flash wipes the filesystem,
so `main.py`, `config.py`, and the non-frozen `lib/` set must be re-deployed
(`run deploy` / the `flash-mpremote` task).

---

## 4. Verify (the part host tests cannot do)

**State the gap plainly:** the host test suite never imports the frozen
modules from firmware. `tests/conftest.py` stubs `machine`/`micropython`/
`uasyncio` and imports `lib/*` as plain source, so a green suite proves the
*logic* is unchanged and says **nothing** about whether the frozen modules
import correctly under the new firmware. Only the bench proves that.

After flashing:

1. Boot and read `/boot.log`. Every frozen module must import; an
   `ImportError` naming one of them is a failed build, not a quirk.
2. Confirm the version line reports the **new** `FIRMWARE_VERSION`,
   `mpy_abi`, and `src=upstream@<tag>@<commit>`. If it still shows the old
   one, the flash did not take.
3. Exercise the operator surfaces: OLED pages, relays, a regulation tick.
4. Soak with `diagnostics.mem_trend_log = True` for several hours, pull
   `system.log`, and compare against the pre-freeze baseline with
   `tools/heap_baseline.py`. That number is the entire justification for the
   freeze — record it.
5. Tick the corresponding rows in [`hw-test-log.md`](../test/hw-test-log.md).

---

## 5. The `.mpy` ABI invariant (do not get this wrong)

A `.mpy` file is only importable by a firmware whose bytecode ABI matches the
`mpy-cross` that produced it. SHA-256 verification does not catch a mismatch —
it proves the bytes arrived intact, not that they mean anything to this
firmware.

**Rule: compile OTA payloads with the `mpy-cross` built from the firmware's own
checkout.** The build script prints its path; use that binary (put it first on
`PATH`) when running the `build-mpy` task.

The system now fails safe rather than silently:

- `build_update_payload.py --compiled` reads the ABI out of the `.mpy` headers
  and stamps `manifest.json` with `mpy_abi`. A tree whose artifacts disagree is
  refused outright — that only happens when two different `mpy-cross` binaries
  built it, and any single stamp would then be a lie.
- On boot, the updater compares that stamp against the running firmware's ABI
  **before verifying or writing anything**, and refuses with a logged
  `verify_fail … mpy_abi mismatch: payload=N firmware=M`. Live code is
  untouched and the payload stays in place so it can be rebuilt.
- Raw-`.py` payloads carry no stamp and skip the check — they recompile
  on-device under whatever firmware is present. Note this is now only useful
  for a **partial** drop: since 2026-07-23 the full raw `.py` app set does not
  fit the flash filesystem, so it is not a whole-app fallback (see §7 step 5).
- `updater.enforce_mpy_abi = False` forces a payload through when you know the
  stamp itself is wrong.

---

## 6. What OTA can and cannot reach after freezing

| Target | OTA? |
|---|---|
| `main.py`, `config.py` / `config.mpy` | yes |
| `lib/build_info.py` | yes |
| Non-frozen `lib/*` (every decision module, and the updater) | yes |
| **Frozen `lib/*`** | **no effect** — the import resolves to the frozen copy |
| `fw_info.py` | no — frozen so a payload cannot forge the firmware identity |
| MicroPython itself / the `.uf2` | **never**. Reflash only. |

A payload naming a frozen module still verifies and applies; the file simply
lands on the filesystem and is ignored. That is a silent no-op, so treat "I
OTA'd it and nothing changed" as the expected symptom, not a bug.

### Emergency hotfix to a frozen module (P5, unproven)

Default RP2 `sys.path` is `['', '.frozen', '/lib']`. In principle: ship the
fixed module in a payload, then in `main.py` (mutable) prepend `/lib` ahead of
`.frozen` before the affected import, and fold the fix into the next firmware
build.

> ⚠ **Bench-verify before relying on this.** Whether a filesystem
> `lib/<mod>.py` already shadows a frozen `lib/<mod>` via the `''` path entry,
> or whether an explicit `sys.path` reorder is required, is import-order
> dependent and has **not** been confirmed on this firmware. It is an open
> hw-test item. Do not plan a release around an unproven escape hatch — this is
> also exactly why `lib/updater.py` itself is never frozen (plan §2.5): if the
> updater were broken, step one would already be unreachable.

---

## 7. Adopting a newer MicroPython

1. `tools/build_firmware.ps1 -Repin` — resolves and locks the newest final
   release. Commit the lockfile change on its own.
2. The script rebuilds `mpy-cross` and the `.uf2` from that ref and
   regenerates `fw_info.py` with the new `MPY_ABI`.
3. Run the host suite. It must not regress — but remember §4: it does not
   exercise the firmware.
4. Bench-soak on device per §4, comparing `post_alloc_b` against the prior
   baseline.
5. **If `MPY_ABI` changed, every field unit's `config.mpy` / `lib/*.mpy` is
   now stale.** Rebuild the compiled payload with the new `mpy-cross` and
   redeploy. The ABI guard turns a stale payload into a logged refusal instead
   of a boot failure, but it does not deliver the fix for you.

   > ⚠ **The raw-`.py` fallback no longer exists.** Earlier revisions of this
   > runbook said "ship a raw-`.py` payload, it recompiles on-device". The
   > 2026-07-23 P0.5 measurement found the raw set **no longer fits the Pico's
   > flash filesystem** — that is why variant A could not even be deployed. A
   > full-app raw payload is therefore not a recovery option; rebuilding the
   > compiled payload, or reflashing plus redeploying, is.
6. **Communicate it.** A `chat-log.md` entry plus a memory file recording the
   new ABI, which modules were re-frozen, and — stated explicitly — whether
   operators must **reflash** (frozen behaviour changed) or can **OTA**
   (mutable-only change). A frozen-set change is a reflash event; say so.

---

## 8. Version surfaces

| Version | Identifies | Lives in | Mutable by OTA? |
|---|---|---|---|
| Firmware | the flashed `.uf2`: MicroPython ref, frozen set, `.mpy` ABI | frozen `fw_info.py` | no |
| App | the mutable `main.py`/`config`/`lib/*` set | `lib/build_info.py` | yes |
| Payload | one OTA drop | `manifest.json` on SD | consumed once |

All three are resolved by [`lib/version.py`](../../lib/version.py), which falls
back to `os.uname()` on a stock firmware and to `"dev"` on the host simulator,
and are printed once per boot to `system.log` and `/boot.log`.

The **OLED INFO page is deferred** — the version surface rides the OLED-screens
rework already in the backlog (plan §11 Q4). Until then the boot-log line is
the operator-facing record.
