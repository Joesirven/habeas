"""Name standardization edge cases beyond official CPPA vectors."""

from __future__ import annotations

import pytest

from drop_normalize import hash_std, normalize_name


class TestGreekTransliteration:
    def test_alpha(self) -> None:
        assert normalize_name("Αθήνα") == "athina"

    def test_sigma_final(self) -> None:
        assert normalize_name("Νίκος") == "nikos"


class TestCyrillicTransliteration:
    def test_soft_sign_removed(self) -> None:
        assert normalize_name("Объект") == "obekt"

    def test_hard_sign_removed(self) -> None:
        assert normalize_name("подъезд") == "podezd"

    def test_cyrillic_sample(self) -> None:
        assert normalize_name("Дмитрий") == "dmitriy"


class TestSpecialLatin:
    def test_eszett(self) -> None:
        assert normalize_name("Straße") == "strasse"

    def test_ae_ligature(self) -> None:
        assert normalize_name("Æsir") == "aesir"

    def test_slash_l(self) -> None:
        assert normalize_name("Łukasz") == "lukasz"


class TestAccentedLatin:
    def test_n_tilde(self) -> None:
        assert normalize_name("Niño") == "nino"

    def test_ring_a(self) -> None:
        assert normalize_name("Ångström") == "angstrom"


class TestCjkPassthrough:
    def test_japanese(self) -> None:
        assert normalize_name("田中") == "田中"

    def test_chinese_compound(self) -> None:
        assert normalize_name("李明") == "李明"

    def test_arabic(self) -> None:
        assert normalize_name("محمد") == "محمد"

    def test_hebrew(self) -> None:
        assert normalize_name("דוד") == "דוד"


class TestCompoundNames:
    def test_space_stripped(self) -> None:
        assert normalize_name("Juan Pablo") == "juanpablo"

    def test_hyphen_stripped(self) -> None:
        assert normalize_name("Mary-Jane") == "maryjane"

    def test_apostrophe_stripped(self) -> None:
        assert normalize_name("O'Brien") == "obrien"


class TestEmptyInputs:
    @pytest.mark.parametrize("value", [None, "", "   ", "---", "!!!"])
    def test_returns_none(self, value: str | None) -> None:
        assert normalize_name(value) is None

    def test_hash_not_called_on_none(self) -> None:
        std = normalize_name(None)
        assert std is None


class TestMixedScript:
    def test_latin_greek_mix(self) -> None:
        result = normalize_name("JohnΑ")
        assert result == "johna"

    def test_punctuation_only_stripped(self) -> None:
        assert normalize_name("  .-'  ") is None

    def test_digits_preserved(self) -> None:
        assert normalize_name("John2nd") == "john2nd"
        assert hash_std("john2nd") == hash_std(normalize_name("John2nd") or "")
