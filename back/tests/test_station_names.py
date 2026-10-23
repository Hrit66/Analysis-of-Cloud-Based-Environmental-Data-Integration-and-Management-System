"""Station-name merge suggestions stay conservative and data-driven."""
from app.services.station_names import normalize_station, suggest_station_merges


class TestNormalization:
    def test_punctuation_and_case_are_ignored_but_words_are_kept(self):
        assert normalize_station("  Netravathi  at   THUMBE ") == "netravathi at thumbe"


class TestSuggestions:
    def test_near_identical_spellings_are_suggested(self):
        suggestions = suggest_station_merges([
            "JIGANI TNAK", "JIGANI TANK", "CHIKKABANVARA", "CHIKKABANWARA",
        ])
        groups = {frozenset(item["variants"]) for item in suggestions}

        assert frozenset({"JIGANI TNAK", "JIGANI TANK"}) in groups
        assert frozenset({"CHIKKABANVARA", "CHIKKABANWARA"}) in groups
        assert all(item["action"].startswith("confirm") for item in suggestions)

    def test_shared_river_name_but_different_place_is_not_merged(self):
        suggestions = suggest_station_merges([
            "Netravathi at Thumbe",
            "Netravathi U/S of Dharmastala",
        ])
        assert suggestions == []

    def test_numbered_sites_are_not_merged(self):
        suggestions = suggest_station_merges(["Hosakerehalli Lake 1", "Hosakerehalli Lake 2"])
        assert suggestions == []

    def test_generic_suffix_does_not_force_a_merge(self):
        suggestions = suggest_station_merges(["Bellandur Lake", "Bellandur"])
        # "lake" is not stripped as filler, so these stay separate unless the
        # configured similarity says otherwise.
        assert all(
            "Bellandur" not in item["variants"] or "Bellandur Lake" not in item["variants"]
            for item in suggestions
        )

    def test_canonical_name_is_reported_and_nothing_is_changed(self):
        suggestions = suggest_station_merges(["HOSAKEREHALLI LAKE", "HOSAKEREHALLI LAKE BENGALURU"])
        assert suggestions
        top = suggestions[0]
        assert top["suggested_name"]
        assert len(top["variants"]) >= 2
        assert "nothing has been changed" in top["action"]
