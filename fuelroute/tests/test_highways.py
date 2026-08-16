from django.test import SimpleTestCase

from fuelroute.services.highways import (
    normalize_highway,
    parse_exit,
    parse_highway,
    parse_route_highways,
)


class ParseHighwayTests(SimpleTestCase):
    def test_finds_first_ref(self):
        self.assertEqual(parse_highway('I-44, EXIT 283 & US-69'), 'I44')

    def test_no_ref_returns_empty(self):
        self.assertEqual(parse_highway('123 Main St'), '')

    def test_normalizes_spacing_and_case(self):
        self.assertEqual(normalize_highway('i 80'), 'I80')
        self.assertEqual(normalize_highway('I-80'), 'I80')


class ParseExitTests(SimpleTestCase):
    def test_plain_number(self):
        self.assertEqual(parse_exit('I-44, EXIT 283 & US-69'), '283')

    def test_letter_suffix_with_hyphen(self):
        self.assertEqual(parse_exit('EXIT 144-B'), '144B')

    def test_letter_suffix_no_separator(self):
        self.assertEqual(parse_exit('I-10, EXIT 138A'), '138A')

    def test_hash_prefix(self):
        self.assertEqual(parse_exit('EXIT #12'), '12')

    def test_no_exit_returns_empty(self):
        self.assertEqual(parse_exit('I-44, Big Cabin'), '')


class ParseRouteHighwaysTests(SimpleTestCase):
    def test_splits_packed_refs(self):
        self.assertEqual(parse_route_highways(['I 90;US 20', '']), {'I90', 'US20'})

    def test_ignores_blank_refs(self):
        self.assertEqual(parse_route_highways(['', None]), set())
