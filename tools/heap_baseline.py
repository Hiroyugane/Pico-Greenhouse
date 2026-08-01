"""Compare steady-state heap use across firmware/deployment variants (punch item P0.5).

The freeze decision in
`the firmware-freeze versioning plan (internal notes)`
turns on one number: how much heap a variant leaves free at steady state.
Freezing modules into the firmware buys RAM but permanently costs OTA reach,
so the council gated it on measuring the two variants that cost nothing first:

    A  baseline          current firmware, raw .py deployment
    B  .mpy-only         same firmware, build-mpy output deployed --compiled
    C  feature-stripped  stock module set, trimmed firmware, nothing frozen

Each variant is soaked on the bench with ``diagnostics.mem_trend_log = True``,
which makes the health loop emit one greppable INFO line per health check:

    [2026-07-22 04:15:00] [INFO] [MAIN] mem trend | pre_alloc_b=201234 \
pre_free_b=44462 post_alloc_b=198600 post_free_b=47096 reclaimed_b=2634 \
used_pct=80.8 tasks=9 buffered=0 queue=0

Pull the resulting ``system.log`` off the SD card once per variant and feed
them here. ``post_alloc_b`` — allocated bytes *after* the loop's gc.collect() —
is the steady-state figure; everything else is churn.

Usage:
    python tools/heap_baseline.py baseline=logs/A-system.log
    python tools/heap_baseline.py A=logs/a.log B=logs/b.log C=logs/c.log
    python tools/heap_baseline.py A=a.log B=b.log --target-free 60000
    python tools/heap_baseline.py A=a.log B=b.log --warmup 10 --json

The first variant on the command line is the baseline every other variant is
differenced against. A label is optional (``python tools/heap_baseline.py
a.log`` labels it by filename), but naming them A/B/C keeps the output
readable next to the plan document.

Host-only tooling: never imported by device code.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# RP2040 MicroPython heap, measured constant on this build (see chat-log
# 2026-07-03 "not a leak"). Override with --heap-bytes if a firmware variant
# changes it — a feature-stripped build very well might.
DEFAULT_HEAP_BYTES = 245_696

# Drop this many leading samples by default: the first health checks run while
# boot-time allocations are still being reclaimed and are not steady state.
DEFAULT_WARMUP = 5

_TREND_RE = re.compile(
    r"mem trend \|"
    r".*?\bpost_alloc_b=(?P<post_alloc>\d+)"
    r".*?\bpost_free_b=(?P<post_free>\d+)"
)
_TIMESTAMP_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]")


class HeapBaselineError(Exception):
    """Raised when a log holds no usable samples."""


def parse_mem_trend(text: str) -> list[dict]:
    """Extract steady-state heap samples from a system.log body.

    Returns one dict per ``mem trend`` line, in file order, each carrying
    ``post_alloc_b``, ``post_free_b`` and the line's timestamp (or ``None``
    when the line is not timestamp-prefixed, e.g. a raw console capture).
    Non-matching lines are ignored, so a whole unfiltered system.log is a
    valid input.
    """
    samples: list[dict] = []
    for line in text.splitlines():
        match = _TREND_RE.search(line)
        if match is None:
            continue
        ts_match = _TIMESTAMP_RE.match(line.strip())
        samples.append(
            {
                "timestamp": ts_match.group("ts") if ts_match else None,
                "post_alloc_b": int(match.group("post_alloc")),
                "post_free_b": int(match.group("post_free")),
            }
        )
    return samples


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def summarize(samples: list[dict], *, warmup: int = DEFAULT_WARMUP, heap_bytes: int = DEFAULT_HEAP_BYTES) -> dict:
    """Reduce raw samples to the figures the freeze decision needs.

    ``warmup`` leading samples are discarded as boot churn — unless that would
    leave nothing, in which case every sample is kept and ``warmup_applied``
    reports 0. ``drift_b`` is the median of the last quarter minus the median
    of the first quarter: a leak signal, not a level.
    """
    if not samples:
        raise HeapBaselineError("no 'mem trend' lines found — was diagnostics.mem_trend_log enabled?")
    warmup_applied = warmup if len(samples) > warmup else 0
    used = samples[warmup_applied:]
    allocs = [s["post_alloc_b"] for s in used]
    frees = [s["post_free_b"] for s in used]

    quarter = max(1, len(allocs) // 4)
    drift = _median(allocs[-quarter:]) - _median(allocs[:quarter])

    median_alloc = _median(allocs)
    return {
        "samples": len(samples),
        "samples_used": len(used),
        "warmup_applied": warmup_applied,
        "first_timestamp": used[0]["timestamp"],
        "last_timestamp": used[-1]["timestamp"],
        "post_alloc_min_b": min(allocs),
        "post_alloc_median_b": median_alloc,
        "post_alloc_max_b": max(allocs),
        "post_free_median_b": _median(frees),
        "post_free_min_b": min(frees),
        "used_pct": 100.0 * median_alloc / heap_bytes,
        "drift_b": drift,
        "heap_bytes": heap_bytes,
    }


def compare(baseline: dict, variant: dict) -> dict:
    """Difference a variant against the baseline.

    ``reclaimed_b`` is positive when the variant allocates *less* than the
    baseline — i.e. the direction the freeze/strip work is trying to move.
    """
    reclaimed = baseline["post_alloc_median_b"] - variant["post_alloc_median_b"]
    return {
        "reclaimed_b": reclaimed,
        "reclaimed_kb": reclaimed / 1024.0,
        "free_gain_b": variant["post_free_median_b"] - baseline["post_free_median_b"],
        "used_pct_delta": variant["used_pct"] - baseline["used_pct"],
    }


def _verdict(variant: dict, target_free_b: int | None) -> str:
    if target_free_b is None:
        return ""
    if variant["post_free_min_b"] >= target_free_b:
        return "MEETS TARGET"
    shortfall = target_free_b - variant["post_free_min_b"]
    return f"short by {shortfall:,} B ({shortfall / 1024.0:.1f} KB)"


def render_report(results: list[tuple[str, dict]], *, target_free_b: int | None = None) -> str:
    """Human-readable table: one row per variant, deltas against the first."""
    base_label, base = results[0]
    lines: list[str] = []
    lines.append(f"heap {base['heap_bytes']:,} B · baseline = {base_label!r} · worst-case free is the gating number")
    lines.append("")
    header = f"{'variant':<14}{'n':>5}{'alloc med':>12}{'free med':>11}{'free min':>11}{'used%':>8}{'drift':>10}"
    lines.append(header)
    lines.append("-" * len(header))
    for label, summary in results:
        lines.append(
            f"{label:<14}{summary['samples_used']:>5}"
            f"{summary['post_alloc_median_b']:>12,.0f}"
            f"{summary['post_free_median_b']:>11,.0f}"
            f"{summary['post_free_min_b']:>11,}"
            f"{summary['used_pct']:>7.1f}%"
            f"{summary['drift_b']:>+10,.0f}"
        )

    if len(results) > 1:
        lines.append("")
        lines.append(f"delta vs {base_label!r} (positive reclaimed = less heap used):")
        for label, summary in results[1:]:
            delta = compare(base, summary)
            lines.append(
                f"  {label:<12} reclaimed {delta['reclaimed_b']:>+9,.0f} B "
                f"({delta['reclaimed_kb']:>+6.1f} KB)   used% {delta['used_pct_delta']:>+5.1f}"
            )

    if target_free_b is not None:
        lines.append("")
        lines.append(f"target: >= {target_free_b:,} B free at the worst sample")
        for label, summary in results:
            lines.append(f"  {label:<12} {_verdict(summary, target_free_b)}")
        meeting = [label for label, summary in results if summary["post_free_min_b"] >= target_free_b]
        lines.append("")
        if meeting:
            lines.append(
                "VERDICT: " + ", ".join(meeting) + " meets the target. If any of these keeps full OTA reach "
                "(baseline / .mpy-only / feature-stripped), DO NOT FREEZE — "
                "ship that variant instead (plan P0.5)."
            )
        else:
            lines.append(
                "VERDICT: no measured variant meets the target. The Tier-1 freeze (plan section 2.1) "
                "is justified — freeze the coldest modules first and re-measure."
            )
    return "\n".join(lines)


def _parse_spec(spec: str) -> tuple[str, Path]:
    """Split a ``label=path`` argument; bare paths are labelled by stem."""
    if "=" in spec:
        label, _, raw_path = spec.partition("=")
        label = label.strip()
        if not label:
            raise argparse.ArgumentTypeError(f"empty label in {spec!r}")
        return label, Path(raw_path.strip())
    path = Path(spec)
    return path.stem, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "logs",
        nargs="+",
        metavar="LABEL=LOG",
        help="One or more system.log files, optionally labelled (e.g. B=logs/mpy-only.log). The first is the baseline.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=DEFAULT_WARMUP,
        help=f"Leading samples to discard as boot churn (default: {DEFAULT_WARMUP})",
    )
    parser.add_argument(
        "--heap-bytes",
        type=int,
        default=DEFAULT_HEAP_BYTES,
        help=f"Total heap for used%% (default: {DEFAULT_HEAP_BYTES})",
    )
    parser.add_argument(
        "--target-free",
        type=int,
        default=None,
        help="Free-bytes headroom target; prints a freeze/no-freeze verdict against it",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of the table")
    args = parser.parse_args(argv)

    if args.warmup < 0:
        parser.error("--warmup must be >= 0")

    results: list[tuple[str, dict]] = []
    for spec in args.logs:
        label, path = _parse_spec(spec)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            return 1
        try:
            summary = summarize(parse_mem_trend(text), warmup=args.warmup, heap_bytes=args.heap_bytes)
        except HeapBaselineError as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            return 1
        summary["source"] = str(path)
        results.append((label, summary))

    if args.json:
        payload = {
            "baseline": results[0][0],
            "variants": {label: summary for label, summary in results},
            "deltas": {label: compare(results[0][1], summary) for label, summary in results[1:]},
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render_report(results, target_free_b=args.target_free))
    return 0


if __name__ == "__main__":
    sys.exit(main())
