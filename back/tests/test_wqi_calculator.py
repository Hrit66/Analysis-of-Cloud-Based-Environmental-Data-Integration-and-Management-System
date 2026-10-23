"""WQI method fingerprint: locks the documented core + extended formulas."""
import pytest

from app.services.wqi_calculator import (
    CORE_PARAMS,
    K_CONST,
    MIN_EXTENDED_PARAMS,
    WQI_CATEGORIES,
    WQI_PARAMS,
    calculate_extended_wqi,
    calculate_wqi,
)


class TestGoldenValues:
    """The review's golden table (core set: pH/DO/BOD, cap 200, floor 0)."""

    def test_ibbalur_2021_12_06(self):
        score, category, sub_indices = calculate_wqi({
            "ph": 7.0999999046, "do": 5.6999998093, "bod": 5.0,
        })

        assert score == pytest.approx(115.03, abs=0.01)
        assert category == "Unsuitable (>100)"
        assert sub_indices == {"ph": 6.67, "do": 92.71, "bod": 166.67}

    def test_ibbalur_2021_05_19(self):
        score, category, sub_indices = calculate_wqi({
            "ph": 6.9000000954, "do": 2.0, "bod": 16.0,
        })

        assert score == pytest.approx(143.94, abs=0.01)
        assert category == "Unsuitable (>100)"
        assert sub_indices["bod"] == pytest.approx(200.0)  # capped at 200

    def test_ibbalur_2020_12_30_core_set_only(self):
        """The 5-parameter sample joins the series on its core three: 96.36."""
        score, _, sub_indices = calculate_wqi({
            "ph": 7.0999999046, "do": 6.1999998093, "bod": 4.0,
            "turbidity": 6.5999999046, "nitrates": 5.75,
        })

        assert score == pytest.approx(96.36, abs=0.01)
        assert set(sub_indices) == {"ph", "do", "bod"}

    def test_allasandra_2021_12_08(self):
        score, category, _ = calculate_wqi({"ph": 8.0, "do": 6.4, "bod": 4.0})

        assert score == pytest.approx(106.56, abs=0.01)
        assert category == "Unsuitable (>100)"

    def test_ph_only_is_not_scored(self):
        assert calculate_wqi({"ph": 7.1}) == (None, None, {})

    def test_do_above_saturation_is_clamped_not_negative(self):
        score, _, sub_indices = calculate_wqi({"ph": 7.1, "do": 15.0, "bod": 5.0})

        assert sub_indices["do"] == 0.0
        assert score == pytest.approx(86.55, abs=0.01)


class TestCoreRules:
    def test_core_requires_all_three_parameters(self):
        assert calculate_wqi({"ph": 7.1, "do": 6.2}) == (None, None, {})
        assert calculate_wqi({"ph": 7.1, "bod": 4.0}) == (None, None, {})
        assert calculate_wqi({"do": 6.2, "bod": 4.0}) == (None, None, {})

    def test_extra_parameters_never_change_the_core_score(self):
        base, _, _ = calculate_wqi({"ph": 7.1, "do": 6.2, "bod": 4.0})
        with_extras, _, _ = calculate_wqi({
            "ph": 7.1, "do": 6.2, "bod": 4.0,
            "turbidity": 6.6, "nitrates": 5.75, "total_coliform": 92_000.0,
        })

        assert with_extras == pytest.approx(base)

    def test_ph_is_symmetric_around_the_ideal(self):
        below, _, _ = calculate_wqi({"ph": 6.5, "do": 6.1, "bod": 4.0})
        above, _, _ = calculate_wqi({"ph": 7.5, "do": 6.1, "bod": 4.0})

        assert below == pytest.approx(above)
        assert below == pytest.approx(101.50, abs=0.01)  # pH term +33.33, not -33.33

    def test_no_parameters_returns_none(self):
        assert calculate_wqi({"ph": None, "do": float("nan")}) == (None, None, {})

    def test_category_boundaries(self):
        bands = [(12.0, "Excellent"), (37.0, "Good"), (60.0, "Poor"), (79.1, "Very Poor"), (150.0, "Unsuitable (>100)")]
        for _score, expected in bands:
            category = next(name for lo, hi, name in WQI_CATEGORIES if lo <= _score < hi)
            assert category == expected


class TestLimitsLocked:
    def test_core_limits(self):
        assert CORE_PARAMS == ("ph", "do", "bod")
        assert WQI_PARAMS["ph"] == {"Si": 8.5, "Vid": 7.0}
        assert WQI_PARAMS["do"] == {"Si": 5.0, "Vid": 14.6}
        assert WQI_PARAMS["bod"] == {"Si": 3.0, "Vid": 0.0}

    def test_extended_limits_include_fixed_nitrate_and_turbidity(self):
        assert WQI_PARAMS["turbidity"] == {"Si": 5.0, "Vid": 0.0}
        # Nitrate limit is 45 mg/L as NO3; imports convert nitrate-N to NO3.
        assert WQI_PARAMS["nitrates"] == {"Si": 45.0, "Vid": 0.0}
        assert K_CONST == pytest.approx(0.06569927, abs=1e-9)


class TestExtendedIndex:
    def test_ibbalur_2020_12_30_extended_five_parameters(self):
        score, category, sub_indices = calculate_extended_wqi({
            "ph": 7.0999999046, "turbidity": 6.5999999046,
            "nitrates": 1.2999999523 * 4.4266, "do": 6.1999998093, "bod": 4.0,
        })

        assert set(sub_indices) == {"ph", "turbidity", "nitrates", "do", "bod"}
        assert sub_indices["turbidity"] == pytest.approx(132.0)
        assert sub_indices["nitrates"] == pytest.approx(12.79, abs=0.01)
        assert score == pytest.approx(102.40, abs=0.01)
        assert category == "Unsuitable (>100)"

    def test_requires_at_least_three_parameters(self):
        assert calculate_extended_wqi({"ph": 7.1, "do": 6.2}) == (None, None, {})
        assert MIN_EXTENDED_PARAMS == 3

    def test_requires_do_or_bod(self):
        assert calculate_extended_wqi({"ph": 7.1, "turbidity": 6.6, "nitrates": 5.75}) == (None, None, {})

    def test_scores_at_limits_equal_100_regardless_of_parameter_count(self):
        three, _, _ = calculate_extended_wqi({"do": 5.0, "bod": 3.0, "turbidity": 5.0})
        four, _, _ = calculate_extended_wqi({"ph": 8.5, "do": 5.0, "bod": 3.0, "fluorides": 1.0})

        assert three == pytest.approx(100.0)
        assert four == pytest.approx(100.0)

    def test_sub_indices_are_clamped_0_to_200(self):
        _, _, sub_indices = calculate_extended_wqi({"do": 10.0, "bod": 16.0, "manganese": 1.0})

        assert sub_indices["bod"] == pytest.approx(200.0)
        assert sub_indices["manganese"] == pytest.approx(200.0)

    def test_unscored_columns_do_not_affect_the_extended_index(self):
        base, _, _ = calculate_extended_wqi({"ph": 7.1, "do": 6.2, "bod": 4.0})
        with_extras, _, _ = calculate_extended_wqi({
            "ph": 7.1, "do": 6.2, "bod": 4.0,
            "total_coliform": 92_000_000.0, "conductivity": 421.0, "ammonia": 0.4,
        })

        assert with_extras == pytest.approx(base)


def test_wqi_limits_are_read_from_the_live_config(monkeypatch):
    """Changing the configured limit changes the score (no cached constants)."""
    from app.services import dataset_config

    values = {"ph": 8.0, "do": 5.0, "bod": 3.0}
    before, _, _ = calculate_wqi(values)
    monkeypatch.setitem(
        dataset_config.WQI["params"], "ph", {"Si": 14.0, "Vid": 7.0}
    )
    after, _, _ = calculate_wqi(values)

    assert after != before
