"""Stage 4.6: the business case arithmetic, input reading and report. Synthetic data with hand-computed answers."""
import json

import pytest

from src.evaluation import businesscase as bc


def test_scenario_times_with_hand_computed_values():
    assert bc.s0(100) == 100
    assert bc.s1(100, 0.5, 0.2) == pytest.approx(70)            # 50 s review + 20 s for the hand-overs
    assert bc.s2(100, 0.5, 0.2, 0.1) == pytest.approx(65)       # 45 s review of the non-eligible + 20 s


def test_cost_and_monthly_saving():
    assert bc.cost(100, 36) == pytest.approx(1.0)
    assert bc.monthly_saving(30, 36, 5000) == pytest.approx(1500)


def test_break_even_is_where_s1_equals_s0():
    h = 0.2
    f = bc.break_even_f(h)
    assert f == pytest.approx(0.8) and bc.s1(100, f, h) == pytest.approx(bc.s0(100))
    assert bc.s1(100, f + 0.1, h) > bc.s0(100)


def test_s2_is_never_slower_than_s1_and_improves_with_more_eligible_tickets():
    assert bc.s2(100, 0.5, 0.2, 0.0) == bc.s1(100, 0.5, 0.2)
    assert bc.s2(100, 0.5, 0.2, 0.3) < bc.s2(100, 0.5, 0.2, 0.1) < bc.s1(100, 0.5, 0.2)


def baseline(secs):
    return [{"practice": True, "position": None, "seconds": 999}] + [{"practice": False, "position": i + 1, "seconds": s} for i, s in enumerate(secs)]


def test_comparators_come_from_the_files_and_exclude_practice():
    comp = bc.comparators(baseline([100, 200, 300, 100, 200, 300]), [{"practice": False, "seconds": 60}, {"practice": False, "seconds": 100}])
    assert comp["untrained"]["seconds"] == pytest.approx(200) and comp["untrained"]["n"] == 6
    assert comp["trained"]["seconds"] == pytest.approx(250) and comp["trained"]["n"] == 2          # last third = the last 2 tickets (200, 300)
    assert comp["heldout"]["seconds"] == pytest.approx(80)


def test_trained_comparator_uses_the_last_third_by_position_not_file_order():
    shuffled = [{"practice": False, "position": 3, "seconds": 30}, {"practice": False, "position": 1, "seconds": 300},
                {"practice": False, "position": 2, "seconds": 200}]
    assert bc.comparators(shuffled, [{"practice": False, "seconds": 1}])["trained"]["seconds"] == 30


def row(tid, action, in_slice=True, ok=True, label_escalate=False):
    return {"ticket_id": tid, "action": action, "in_slice": in_slice, "end_to_end_ok": ok, "label_escalate": label_escalate}


def auto(k=1, n=10):
    return {"eligible_of_all": {"k": k, "n": n, "low": 0.01, "high": 0.4}}


def test_agent_shares_count_handovers_wrong_proposals_and_missed_escalations():
    rows = [row("T-1", "route_to_human"), row("T-2", "escalate_human", label_escalate=True), row("T-3", "provide_info"),
            row("T-4", "propose_refund"), row("T-5", "propose_refund", ok=False), row("T-6", "propose_cancellation", in_slice=False),
            row("T-7", "provide_info", label_escalate=True), row("T-8", "decline_policy"), row("T-9", "provide_info"), row("T-10", "provide_info")]
    s = bc.agent_shares({"rows": rows}, auto())
    assert s["h"] == 0.2 and s["handed"] == 2 and s["e"] == 0.1 and s["proposals"] == 3
    assert s["wrong_proposals"] == ["T-5", "T-6"] and s["missed_escalations"] == ["T-7"]


def case(build_hours=None):
    comp = {"untrained": {"seconds": 100.0, "n": 40, "label": "U"}, "heldout": {"seconds": 50.0, "n": 40, "label": "H"}}
    shares = bc.agent_shares({"rows": [row(f"T-{i}", "route_to_human" if i < 2 else "provide_info") for i in range(10)]}, auto())
    return bc.build(comp, shares, build_hours)


def test_build_base_case_values():
    c = case()
    u = c["comparators"]["untrained"]
    assert c["break_even_f"] == pytest.approx(0.8)
    assert u["base_seconds"] == {"S0": 100.0, "S1": pytest.approx(70), "S2": pytest.approx(65)}
    assert u["base_cost"]["S0"] == pytest.approx(100 / 3600 * 25)
    assert u["monthly"][25][5000]["S1"] == pytest.approx(bc.monthly_saving(30, 25, 5000))
    assert u["monthly"][60][20000]["S2"] > u["monthly"][15][1000]["S2"]


def test_review_share_grid_shows_a_cost_when_review_is_slower_than_break_even():
    row100 = case()["comparators"]["untrained"]["s1_saving_per_ticket"]["100%"]
    assert all(v < 0 for v in row100.values())                                    # f = 100% with 20% hand-overs costs more than manual
    assert all(v > 0 for v in case()["comparators"]["untrained"]["s1_saving_per_ticket"]["25%"].values())


def test_eligible_sensitivity_is_clamped_and_ordered():
    s = case()["comparators"]["untrained"]["s2_by_eligible_share"]
    assert list(s) == ["0%", "10%", "20%"]
    vals = [v["monthly_saving"] for v in s.values()]
    assert vals == sorted(vals)


def test_payback_months_uses_build_hours_at_the_base_labour_cost():
    c = case(build_hours=100)
    m = c["comparators"]["untrained"]["monthly"][25][5000]["S1"]
    assert c["comparators"]["untrained"]["payback_months_s1_base"] == pytest.approx(100 * 25 / m)
    assert "payback_months_s1_base" not in case()["comparators"]["untrained"]


def test_payback_is_none_when_there_is_no_saving():
    comp = {"x": {"seconds": 100.0, "n": 1, "label": "X"}}
    shares = bc.agent_shares({"rows": [row(f"T-{i}", "route_to_human") for i in range(10)]}, auto(0))     # everything handed over: S1 costs more
    assert bc.build(comp, shares, 50)["comparators"]["x"]["payback_months_s1_base"] is None


def test_render_leads_with_the_caveats_and_the_break_even():
    text = bc.render(case(), "run-x", "2026-10-14")
    for needle in ("not a return on investment", "No review time was measured", "80% of the time", "Wrong proposals", "stage 4.5 simulation"):
        assert needle in text
    assert "Payback" not in text and "Payback" in bc.render(case(100), "run-x", "2026-10-14", 100)


def test_command_refuses_missing_inputs_and_writes_outputs(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    assert bc.main(["--run", str(run), "--report", str(tmp_path / "r.md")]) == 2
    (run / "score.json").write_text(json.dumps({"rows": [row(f"T-{i}", "provide_info") for i in range(10)]}), encoding="utf-8")
    (run / "autoresolve.json").write_text(json.dumps(auto()), encoding="utf-8")
    base, man = tmp_path / "b.jsonl", tmp_path / "m.jsonl"
    base.write_text("".join(json.dumps(r) + "\n" for r in baseline([100, 200, 300])), encoding="utf-8")
    man.write_text(json.dumps({"practice": False, "seconds": 80}) + "\n", encoding="utf-8")
    assert bc.main(["--run", str(run), "--baseline", str(base), "--manual", str(man), "--report", str(tmp_path / "r.md")]) == 0
    assert "Business Case" in (tmp_path / "r.md").read_text(encoding="utf-8") and (run / "businesscase.json").exists()


def test_payback_is_none_not_a_crash_when_the_saving_is_exactly_zero():
    comp = {"x": {"seconds": 100.0, "n": 1, "label": "X"}}
    shares = bc.agent_shares({"rows": [row(f"T-{i}", "route_to_human" if i < 5 else "provide_info") for i in range(10)]}, auto(0))   # h = 50% = break-even at f = 50%
    assert bc.build(comp, shares, 50)["comparators"]["x"]["payback_months_s1_base"] is None


def test_base_case_table_shows_cents_and_the_share_of_time_saved():
    text = bc.render(case(), "run-x", "2026-10-14")
    assert "| $0.69 | $0.49 | $0.45 | 30% / 35% |" in text          # T = 100 s at $25/h: S0 69c, S1 70 s = 49c, S2 65 s = 45c