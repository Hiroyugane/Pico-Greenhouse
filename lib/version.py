# Version helper - firmware + app identity in one place
# Dennis Hiro, 2026-07-22
#
# Three versions describe a running greenhouse and they answer different
# questions (plan section 4.1):
#
#   firmware  the flashed .uf2: which MicroPython, which frozen module set,
#             and — the load-bearing part — which .mpy bytecode ABI it can
#             import. Frozen into the image as fw_info.py, so an OTA payload
#             cannot overwrite or forge it.
#   app       the mutable main.py/config.py/lib/* set, stamped into
#             lib/build_info.py by tools/build_update_payload.py.
#   payload   one OTA drop; lives in the SD manifest, not here.
#
# Resolution is a triple fallback, the same shape oled_display already uses
# for build_info: frozen fw_info -> os.uname() on a stock firmware -> "dev" on
# the host simulator. A unit must be able to say what it is even when it is
# running a firmware this repo never built.
#
# Runs once at boot. No allocation in any tick path.

_UNKNOWN_ABI = 0


def _mpy_abi_from_sys():
    """Low byte of ``sys.implementation._mpy`` — the ABI this runtime imports.

    Returns ``_UNKNOWN_ABI`` (0) when the attribute is absent, which is the
    case on CPython and on very old MicroPython builds. Callers must treat 0
    as "cannot compare", never as a real ABI number.
    """
    try:
        import sys

        return int(sys.implementation._mpy) & 0xFF  # type: ignore[attr-defined]
    except Exception:
        return _UNKNOWN_ABI


def resolve_firmware():
    """Return ``(version, mpy_abi, source, frozen_at)`` for the running firmware.

    Order matters: the frozen module wins because it is the only source that
    is guaranteed to describe *this* image. ``os.uname()`` is the honest
    second-best on a stock MicroPython — it names the build but not the frozen
    set, so ``source`` reports ``"uname"`` to make clear the identity is
    inferred rather than stamped.
    """
    try:
        import fw_info

        return (
            fw_info.FIRMWARE_VERSION,
            int(fw_info.MPY_ABI),
            fw_info.MPY_SOURCE,
            getattr(fw_info, "FROZEN_AT", "?"),
        )
    except Exception:
        pass

    try:
        import os
        import sys

        if sys.implementation.name == "micropython":
            uname = os.uname()  # type: ignore[attr-defined]
            return (
                "%s/%s" % (uname.release, uname.version.split(" ")[0]),
                _mpy_abi_from_sys(),
                "uname",
                "?",
            )
    except Exception:
        pass

    return ("dev", _UNKNOWN_ABI, "host", "?")


def resolve_frozen_modules():
    """Names this firmware froze, as a tuple, or ``()`` when unknowable.

    ``()`` means "cannot tell", never "froze nothing" — a stock MicroPython and
    a pre-2026-07-28 custom image are indistinguishable from here. The updater's
    prune sweep treats the empty tuple as a refusal to delete rather than as
    permission to delete everything, which is the only reading that is safe on
    a board whose ``/lib`` holds the sole copy of a module.
    """
    try:
        import fw_info

        return tuple(str(name) for name in fw_info.FROZEN_MODULES)
    except Exception:
        return ()


def resolve_app():
    """Return ``(app_version, build_time)`` from the OTA-stamped build_info."""
    try:
        from lib.build_info import BUILD_TIME, VERSION

        return (VERSION, BUILD_TIME)
    except ImportError:
        try:
            from build_info import BUILD_TIME, VERSION  # on-device sys.path

            return (VERSION, BUILD_TIME)
        except ImportError:
            return ("dev", "?")


FIRMWARE_VERSION, MPY_ABI, MPY_SOURCE, FROZEN_AT = resolve_firmware()
FROZEN_MODULES = resolve_frozen_modules()
APP_VERSION, BUILD_TIME = resolve_app()


def current_frozen_modules():
    """The frozen module set to prune ``/lib`` shadows against, or ``()``."""
    return FROZEN_MODULES


def current_mpy_abi():
    """The ABI to compare an OTA payload's stamp against, or ``None`` if unknown.

    Prefers the frozen ``fw_info.MPY_ABI``; falls back to what the runtime
    reports. ``None`` means "no comparison is possible" — the updater must
    skip its guard rather than guess, because a guess either bricks a good
    payload or waves a bad one through.
    """
    if MPY_ABI:
        return MPY_ABI
    runtime_abi = _mpy_abi_from_sys()
    return runtime_abi or None


def describe():
    """One-line identity string for the boot log (plan section 4.5)."""
    return "fw=%s app=%s mpy_abi=%s src=%s built=%s" % (
        FIRMWARE_VERSION,
        APP_VERSION,
        MPY_ABI,
        MPY_SOURCE,
        BUILD_TIME,
    )
