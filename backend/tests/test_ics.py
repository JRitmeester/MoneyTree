from app.services.ics import is_ics_text


class TestIsIcsText:
    def test_matches_full_counterparty_name(self):
        assert is_ics_text("International Card Services BV") is True

    def test_matches_full_name_case_insensitive(self):
        assert is_ics_text("international card services b.v.") is True

    def test_matches_standalone_ics_word(self):
        assert is_ics_text("Betaalpas ICS Rekening") is True

    def test_does_not_match_substring_inside_other_word(self):
        assert is_ics_text("PICSNIC") is False

    def test_does_not_match_unrelated_text(self):
        assert is_ics_text("Albert Heijn") is False

    def test_handles_none_parts(self):
        assert is_ics_text(None, None) is False

    def test_checks_multiple_parts(self):
        assert is_ics_text(None, "International Card Services") is True
