"""Tests for tools/heap_baseline.py — the P0.5 freeze-decision measurement tool."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.heap_baseline import (  # noqa: E402
    DEFAULT_HEAP_BYTES,
    HeapBaselineError,
    compare,
    main,
    parse_mem_trend,
    render_report,
    summarize,
)


def _trend_line(post_alloc: int, post_free: int, ts: str = "2026-07-22 04:15:00") -> str:
    return (
        f"[{ts}] [INFO] [MAIN] mem trend | pre_alloc_b={post_alloc + 2000} "
        f"pre_free_b={post_free - 2000} post_alloc_b={post_alloc} post_free_b={post_free} "
        f"reclaimed_b=2000 used_pct=80.8 tasks=9 buffered=0 queue=0"
    )


class TestParseMemTrend:
    def test_extracts_post_gc_figures(self):
        text = "\n".join([_trend_line(198_600, 47_096), _trend_line(198_900, 46_796)])
        samples = parse_mem_trend(text)
        assert [s["post_alloc_b"] for s in samples] == [198_600, 198_900]
        assert samples[0]["post_free_b"] == 47_096
        assert samples[0]["timestamp"] == "2026-07-22 04:15:00"

    def test_ignores_unrelated_lines(self):
        text = "\n".join(
            [
                "[2026-07-22 04:14:00] [INFO] [MAIN] System startup (reset_cause=PWRON)",
                _trend_line(198_600, 47_096),
                "[2026-07-22 04:16:00] [WARN] [SD] write failed",
            ]
        )
        assert len(parse_mem_trend(text)) == 1

    def test_untimestamped_console_capture_still_parses(self):
        samples = parse_mem_trend("mem trend | post_alloc_b=100 post_free_b=200")
        assert samples[0]["timestamp"] is None
        assert samples[0]["post_alloc_b"] == 100

    def test_empty_input_yields_no_samples(self):
        assert parse_mem_trend("") == []


class TestSummarize:
    def test_raises_when_no_samples(self):
        with pytest.raises(HeapBaselineError, match="mem_trend_log"):
            summarize([])

    def test_drops_warmup_samples(self):
        samples = [{"timestamp": None, "post_alloc_b": 300_000, "post_free_b": 1_000} for _ in range(3)]
        samples += [{"timestamp": None, "post_alloc_b": 200_000, "post_free_b": 45_000} for _ in range(7)]
        summary = summarize(samples, warmup=3)
        assert summary["warmup_applied"] == 3
        assert summary["samples_used"] == 7
        # The boot-churn spike is gone from the steady-state figures.
        assert summary["post_alloc_max_b"] == 200_000

    def test_warmup_not_applied_when_it_would_empty_the_set(self):
        samples = [{"timestamp": None, "post_alloc_b": 100, "post_free_b": 200}]
        summary = summarize(samples, warmup=5)
        assert summary["warmup_applied"] == 0
        assert summary["samples_used"] == 1

    def test_used_pct_against_heap_total(self):
        samples = [{"timestamp": None, "post_alloc_b": DEFAULT_HEAP_BYTES // 2, "post_free_b": 1}]
        summary = summarize(samples, warmup=0)
        assert summary["used_pct"] == pytest.approx(50.0)

    def test_drift_is_positive_when_allocation_climbs(self):
        samples = [{"timestamp": None, "post_alloc_b": 100_000 + i * 1_000, "post_free_b": 1} for i in range(8)]
        summary = summarize(samples, warmup=0)
        assert summary["drift_b"] > 0

    def test_drift_is_flat_for_a_stable_heap(self):
        samples = [{"timestamp": None, "post_alloc_b": 198_600, "post_free_b": 47_096} for _ in range(20)]
        summary = summarize(samples, warmup=0)
        assert summary["drift_b"] == 0


class TestCompare:
    def test_reclaimed_is_positive_when_the_variant_allocates_less(self):
        base = summarize([{"timestamp": None, "post_alloc_b": 198_600, "post_free_b": 47_096}], warmup=0)
        variant = summarize([{"timestamp": None, "post_alloc_b": 160_000, "post_free_b": 85_696}], warmup=0)
        delta = compare(base, variant)
        assert delta["reclaimed_b"] == 38_600
        assert delta["free_gain_b"] == 38_600
        assert delta["used_pct_delta"] < 0


class TestRenderReport:
    def _summary(self, alloc: int, free: int):
        return summarize([{"timestamp": None, "post_alloc_b": alloc, "post_free_b": free}], warmup=0)

    def test_no_freeze_verdict_when_a_variant_meets_the_target(self):
        results = [("A", self._summary(198_600, 47_096)), ("B", self._summary(160_000, 85_696))]
        report = render_report(results, target_free_b=60_000)
        assert "DO NOT FREEZE" in report
        assert "B meets the target" in report

    def test_freeze_justified_when_nothing_meets_the_target(self):
        results = [("A", self._summary(198_600, 47_096)), ("B", self._summary(195_000, 50_696))]
        report = render_report(results, target_free_b=60_000)
        assert "freeze" in report.lower()
        assert "DO NOT FREEZE" not in report

    def test_target_section_omitted_without_a_target(self):
        report = render_report([("A", self._summary(198_600, 47_096))])
        assert "VERDICT" not in report


class TestCli:
    def _write_log(self, tmp_path: Path, name: str, allocs: list[int]) -> Path:
        path = tmp_path / name
        path.write_text("\n".join(_trend_line(a, DEFAULT_HEAP_BYTES - a) for a in allocs))
        return path

    def test_labelled_variants_render(self, tmp_path, capsys):
        a = self._write_log(tmp_path, "a.log", [198_600] * 10)
        b = self._write_log(tmp_path, "b.log", [160_000] * 10)
        assert main([f"A={a}", f"B={b}", "--warmup", "0"]) == 0
        out = capsys.readouterr().out
        assert "A" in out and "B" in out
        assert "reclaimed" in out

    def test_bare_path_is_labelled_by_stem(self, tmp_path, capsys):
        a = self._write_log(tmp_path, "baseline.log", [198_600] * 10)
        assert main([str(a), "--warmup", "0"]) == 0
        assert "baseline" in capsys.readouterr().out

    def test_json_output_carries_deltas(self, tmp_path, capsys):
        import json

        a = self._write_log(tmp_path, "a.log", [198_600] * 10)
        b = self._write_log(tmp_path, "b.log", [160_000] * 10)
        assert main([f"A={a}", f"B={b}", "--warmup", "0", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["baseline"] == "A"
        assert payload["deltas"]["B"]["reclaimed_b"] == 38_600

    def test_missing_file_exits_nonzero(self, tmp_path, capsys):
        assert main([str(tmp_path / "nope.log")]) == 1
        assert "cannot read" in capsys.readouterr().err

    def test_log_without_trend_lines_exits_nonzero(self, tmp_path, capsys):
        path = tmp_path / "quiet.log"
        path.write_text("[2026-07-22 04:14:00] [INFO] [MAIN] System startup\n")
        assert main([str(path)]) == 1
        assert "mem_trend_log" in capsys.readouterr().err
