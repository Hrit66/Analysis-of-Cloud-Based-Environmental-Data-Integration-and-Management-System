"""CPCB designated-best-use classification: golden values and honesty rules."""
from app.services.cpcb_classes import CPCB_USE_CLASSES, classify_sample


class TestGoldenSamples:
    def test_class_a_full_check(self):
        result = classify_sample({
            "ph": 7.5, "do": 7.0, "bod": 1.5, "total_coliform": 30.0,
        })

        assert result["class"] == "A"
        assert result["partial"] is False
        assert result["missing"] == []

    def test_ibbalur_2021_12_06_is_class_d(self):
        """A/B/C fail on coliform and BOD; D passes with ammonia as upper bound."""
        result = classify_sample({
            "ph": 7.0999999046, "do": 5.6999998093, "bod": 5.0,
            "total_coliform": 92000.0, "ammonia": 1.1799999475, "conductivity": 727.0,
        })

        assert result["class"] == "D"
        assert result["partial"] is False
        assert result["approximate"] is True
        assert "total NH3-N" in result["note"]

    def test_ibbalur_2021_05_19_is_class_e_partial(self):
        """DO 2.0 fails A-D; E passes on pH and conductivity but SAR/boron are not stored."""
        result = classify_sample({
            "ph": 6.9000000954, "do": 2.0, "bod": 16.0,
            "total_coliform": 92000.0, "ammonia": 0.4, "conductivity": 656.0,
        })

        assert result["class"] == "E"
        assert result["partial"] is True
        assert any("adsorption" in m for m in result["missing"])
        assert any("boron" in m for m in result["missing"])


class TestHonestyRules:
    def test_missing_coliform_marks_partial_instead_of_guessing(self):
        result = classify_sample({"ph": 7.5, "do": 7.0, "bod": 1.5})

        assert result["class"] == "A"
        assert result["partial"] is True
        assert "total coliform" in result["missing"]

    def test_total_ammonia_above_limit_leaves_d_unverifiable(self):
        """Total NH3-N > 1.2 cannot prove the free-ammonia criterion."""
        result = classify_sample({
            "ph": 7.1, "do": 5.7, "bod": 5.0, "total_coliform": 92000.0, "ammonia": 2.0,
        })

        assert result["class"] == "D"
        assert result["partial"] is True
        assert any("free ammonia" in m for m in result["missing"])

    def test_failing_all_classes_returns_below_e(self):
        result = classify_sample({"ph": 4.0, "do": 1.0, "bod": 20.0})

        assert result["class"] == "Below E"
        assert result["partial"] is False

    def test_no_parameters_returns_not_classifiable(self):
        result = classify_sample({})

        assert result["class"] is None
        assert result["partial"] is True


class TestLimitsTable:
    def test_table_locked_to_is_2296(self):
        table = {entry["class"]: entry["criteria"] for entry in CPCB_USE_CLASSES}

        assert table["A"] == [
            ("ph", "range", 6.5, 8.5), ("do", "min", 6.0), ("bod", "max", 2.0),
            ("total_coliform", "max", 50.0),
        ]
        assert table["B"] == [
            ("ph", "range", 6.5, 8.5), ("do", "min", 5.0), ("bod", "max", 3.0),
            ("total_coliform", "max", 500.0),
        ]
        assert table["C"] == [
            ("ph", "range", 6.0, 9.0), ("do", "min", 4.0), ("bod", "max", 3.0),
            ("total_coliform", "max", 5000.0),
        ]
        assert table["D"] == [("ph", "range", 6.5, 8.5), ("do", "min", 4.0), ("ammonia_free", "max", 1.2)]
        assert table["E"] == [
            ("ph", "range", 6.0, 8.5), ("conductivity", "max", 2250.0),
            ("sar", "max", 26.0), ("boron", "max", 2.0),
        ]
