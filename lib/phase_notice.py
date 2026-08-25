# Phase-Notice Store - persistence for the acknowledged grow phase
# Dennis Hiro, 2026-08-25
#
# The regulation engine changes grow phase on its own, every few weeks, and the
# operator has to SEE that it happened. The OLED notice that says so is
# acknowledge-required rather than timed out — which only works if the
# acknowledgement outlives a reset, so a controller that reboots the night it
# advanced (or that was unplugged across a phase boundary entirely) puts the
# notice back up instead of losing it.
#
# One line in one file on internal flash: the name of the last phase a human
# confirmed. Deliberately the same mechanism ServiceReminder uses for its
# last-serviced timestamp — same shape, same total tolerance of a missing or
# unreadable file, and the same reason for staying off the SD card: the notice
# has to work with the card pulled.


class PhaseNoticeStore:
    """Remembers which grow phase the operator has already acknowledged.

    Attributes:
        storage_path (str): file the phase name is kept in (falsy = no
            persistence at all, which degrades to "notice every boot").
    """

    def __init__(self, storage_path: str = "/phase_ack.txt", logger=None):
        """
        Args:
            storage_path (str): absolute path of the one-line state file.
            logger: optional EventLogger for debug/diagnostic messages.
        """
        self.storage_path = storage_path
        self._logger = logger

    # -- storage ----------------------------------------------------------

    def last_acknowledged(self):
        """Return the stored phase name, or None when nothing is stored.

        A missing, empty or unreadable file is not an error — it is a
        controller that has never had a phase confirmed on it.
        """
        if not self.storage_path:
            return None
        try:
            with open(self.storage_path, "r") as f:
                value = f.read().strip()
            if self._logger:
                self._logger.debug(
                    "PhaseNotice",
                    "loaded acknowledged phase",
                    path=self.storage_path,
                    value=value or "(empty)",
                )
            return value if value else None
        except Exception:
            if self._logger:
                self._logger.debug("PhaseNotice", "no acknowledged phase stored", path=self.storage_path)
            return None

    def acknowledge(self, phase) -> None:
        """Persist ``phase`` as acknowledged. Never raises.

        A write that fails costs one repeated notice after the next reset,
        which is the safe direction to fail in — so it is logged and swallowed
        rather than propagated into the button callback that called it.
        """
        if not self.storage_path or not phase:
            return
        try:
            with open(self.storage_path, "w") as f:
                f.write(phase)
            if self._logger:
                self._logger.debug("PhaseNotice", "saved acknowledged phase", path=self.storage_path, value=phase)
        except Exception as e:
            if self._logger:
                self._logger.error("PhaseNotice", f"Failed saving acknowledged phase: {e}")
            else:
                print(f"[PhaseNotice] ERROR saving acknowledged phase: {e}")

    # -- boot decision ----------------------------------------------------

    def needs_notice(self, active_phase) -> bool:
        """Should a notice be raised for ``active_phase`` at boot?

        True when the controller resolved a phase the operator has not
        confirmed — which covers both "it advanced and then reset before
        anyone saw it" and "it was switched off across a phase boundary".

        A controller with no stored phase at all SEEDS itself with the active
        one and answers False: the very first phase of a grow is the state the
        operator just configured by hand, and announcing it back to them would
        train them to dismiss the notice without reading it.
        """
        if not active_phase:
            return False
        stored = self.last_acknowledged()
        if stored is None:
            self.acknowledge(active_phase)
            if self._logger:
                self._logger.info("PhaseNotice", f"Seeded acknowledged phase: {active_phase}")
            return False
        return stored != active_phase
