import unittest

from dicomforge import DicomDataset, Tag
from dicomforge.charset import (
    PersonName,
    can_encode_text,
    coerce_person_name,
    dataset_character_set,
    decode_text,
    encode_text,
    normalize_specific_character_set,
    preferred_specific_character_set,
    python_codecs_for_character_set,
)
from dicomforge.errors import CharacterSetError


class CharacterSetTests(unittest.TestCase):
    def test_specific_character_set_tag_registered(self):
        self.assertEqual(Tag.SpecificCharacterSet, Tag.parse("SpecificCharacterSet"))
        self.assertEqual(str(Tag.SpecificCharacterSet), "(0008,0005)")

    def test_normalizes_empty_to_default_ascii(self):
        self.assertEqual(normalize_specific_character_set(None), ("ISO_IR 6",))
        self.assertEqual(python_codecs_for_character_set(None), ("ascii",))

    def test_normalizes_utf8_aliases(self):
        self.assertEqual(normalize_specific_character_set("UTF-8"), ("ISO_IR 192",))
        self.assertEqual(preferred_specific_character_set("utf-8"), "ISO_IR 192")
        self.assertEqual(python_codecs_for_character_set("ISO_IR 192"), ("utf-8",))

    def test_dataset_character_set_reads_tag(self):
        ds = DicomDataset({Tag.SpecificCharacterSet: "ISO_IR 192"})
        self.assertEqual(dataset_character_set(ds), ("ISO_IR 192",))

    def test_utf8_roundtrip_for_japanese_name(self):
        text = "山田太郎"
        encoded = encode_text(text, "ISO_IR 192")
        self.assertEqual(decode_text(encoded, "ISO_IR 192"), text)

    def test_iso2022_japanese_roundtrip(self):
        text = "山田太郎"
        encoded = encode_text(text, "ISO 2022 IR 87")
        self.assertIn(b"\x1b", encoded)
        self.assertEqual(decode_text(encoded, "ISO 2022 IR 87"), text)

    def test_multivalue_iso2022_prefers_escape_aware_decoder(self):
        text = "山田太郎"
        encoded = text.encode("iso2022_jp")

        decoded = decode_text(encoded, ["ISO_IR 6", "ISO 2022 IR 87"])

        self.assertEqual(decoded, text)

    def test_canonical_iso2022_ascii_designator_is_supported(self):
        text = "山田太郎"
        encoded = text.encode("iso2022_jp")

        decoded = decode_text(encoded, ["ISO 2022 IR 6", "ISO 2022 IR 87"])

        self.assertEqual(decoded, text)
        self.assertEqual(
            python_codecs_for_character_set(["ISO 2022 IR 6", "ISO 2022 IR 87"]),
            ("iso2022_jp", "ascii"),
        )

    def test_iso2022_korean_roundtrip(self):
        text = "홍길동"
        encoded = encode_text(text, "ISO 2022 IR 149")
        self.assertIn(b"\x1b", encoded)
        self.assertEqual(decode_text(encoded, "ISO 2022 IR 149"), text)

    def test_gb18030_chinese_roundtrip(self):
        text = "张伟"
        encoded = encode_text(text, "GB18030")
        self.assertEqual(decode_text(encoded, "GB18030"), text)

    def test_ascii_rejects_non_ascii_text(self):
        with self.assertRaises(CharacterSetError):
            encode_text("山田", None)
        self.assertFalse(can_encode_text("山田", None))

    def test_unsupported_charset_raises_clear_error(self):
        with self.assertRaisesRegex(CharacterSetError, "not supported"):
            python_codecs_for_character_set("ISO 2022 IR 13")

    def test_person_name_parse_and_format(self):
        name = PersonName.parse("Yamada^Taro^^Dr^PhD=山田^太郎=やまだ^たろう")

        self.assertEqual(name.family_name, "Yamada")
        self.assertEqual(name.given_name, "Taro")
        self.assertEqual(name.name_prefix, "Dr")
        self.assertEqual(name.name_suffix, "PhD")
        self.assertEqual(name.ideographic, "山田^太郎")
        self.assertEqual(name.phonetic, "やまだ^たろう")
        self.assertEqual(name.display(), "Dr Taro Yamada, PhD")
        self.assertEqual(str(name), "Yamada^Taro^^Dr^PhD=山田^太郎=やまだ^たろう")

    def test_person_name_display_falls_back_to_alternate_groups(self):
        self.assertEqual(PersonName(ideographic="山田^太郎").display(), "山田 太郎")
        self.assertEqual(PersonName(phonetic="やまだ^たろう").display(), "やまだ たろう")

    def test_coerce_person_name_passthrough(self):
        name = PersonName("Doe", "Jane")

        self.assertIs(coerce_person_name(name), name)
        self.assertEqual(coerce_person_name("Doe^Jane").display(), "Jane Doe")

    def test_person_name_rejects_extra_groups(self):
        with self.assertRaisesRegex(CharacterSetError, "three"):
            PersonName.parse("A=B=C=D")

    def test_person_name_rejects_extra_alphabetic_components(self):
        with self.assertRaisesRegex(CharacterSetError, "five"):
            PersonName.parse("A^B^C^D^E^F")

    def test_person_name_rejects_embedded_separators_when_formatting(self):
        with self.assertRaisesRegex(CharacterSetError, "cannot contain"):
            PersonName("Family^Bad").to_dicom_string()
        with self.assertRaisesRegex(CharacterSetError, "cannot contain"):
            PersonName("Family", ideographic="山田=太郎").to_dicom_string()


if __name__ == "__main__":
    unittest.main()
