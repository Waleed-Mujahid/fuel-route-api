"""Exercises the import command's geocoding-tier selection against small,
synthetic fixture files -- no network, no dependency on the real
7,500-row dataset or a live highway_exits.csv.
"""

import csv
import json
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from fuelroute.models import FuelStation


def _write_csv(path: Path, header: list[str], rows: list[list[str]]):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


class ImportPrecisionTests(TestCase):
    def setUp(self):
        self.tmp = Path(self._testMethodName + '_fixtures')
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))

        self.csv_path = self.tmp / 'fuel-prices.csv'
        self.cities_path = self.tmp / 'us_cities.csv'
        self.overrides_path = self.tmp / 'overrides.json'
        self.exits_path = self.tmp / 'highway_exits.csv'

        _write_csv(
            self.cities_path,
            ['CITY', 'STATE_CODE', 'LATITUDE', 'LONGITUDE'],
            [['BIG CABIN', 'OK', '36.5378', '-95.1978']],
        )
        self.overrides_path.write_text(json.dumps({}))

    def _run_import(self):
        out = StringIO()
        call_command(
            'import_fuel_prices',
            csv_path=str(self.csv_path),
            cities_path=str(self.cities_path),
            overrides_path=str(self.overrides_path),
            exits_path=str(self.exits_path),
            stdout=out,
        )
        return out.getvalue()

    def test_exit_lookup_preferred_over_city_centroid(self):
        _write_csv(
            self.csv_path,
            ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID',
             'Retail Price'],
            [['7', 'WOODSHED', 'I-44, EXIT 283 & US-69', 'Big Cabin', 'OK', '307', '3.00']],
        )
        _write_csv(
            self.exits_path,
            ['state', 'highway', 'exit', 'latitude', 'longitude'],
            [['OK', 'I44', '283', '36.5679', '-95.2133']],
        )

        self._run_import()

        station = FuelStation.objects.get(opis_id=7)
        self.assertEqual(station.geocode_precision, 'exit')
        self.assertAlmostEqual(station.latitude, 36.5679)
        self.assertAlmostEqual(station.longitude, -95.2133)

    def test_falls_back_to_city_centroid_when_exit_not_in_lookup(self):
        _write_csv(
            self.csv_path,
            ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID',
             'Retail Price'],
            [['7', 'WOODSHED', 'I-44, EXIT 999 & US-69', 'Big Cabin', 'OK', '307', '3.00']],
        )
        _write_csv(self.exits_path, ['state', 'highway', 'exit', 'latitude', 'longitude'], [])

        self._run_import()

        station = FuelStation.objects.get(opis_id=7)
        self.assertEqual(station.geocode_precision, 'city')
        self.assertAlmostEqual(station.latitude, 36.5378)
        self.assertAlmostEqual(station.longitude, -95.1978)

    def test_missing_exits_file_falls_back_cleanly(self):
        _write_csv(
            self.csv_path,
            ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID',
             'Retail Price'],
            [['7', 'WOODSHED', 'I-44, EXIT 283 & US-69', 'Big Cabin', 'OK', '307', '3.00']],
        )
        # self.exits_path deliberately not written.

        self._run_import()

        station = FuelStation.objects.get(opis_id=7)
        self.assertEqual(station.geocode_precision, 'city')

    def test_duplicate_opis_id_rows_are_merged_keeping_cheapest_price(self):
        _write_csv(
            self.csv_path,
            ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID',
             'Retail Price'],
            [
                ['7', 'WOODSHED OF BIG CABIN', 'I-44, EXIT 283 & US-69', 'Big Cabin', 'OK', '307', '3.50'],
                ['7', 'WOODSHED', 'I-44, EXIT 283 & US-69', 'Big Cabin', 'OK', '307', '3.10'],
                ['7', 'WOODSHED OF BIG CABIN', 'I-44, EXIT 283 & US-69', 'Big Cabin', 'OK', '307', '3.30'],
            ],
        )
        _write_csv(
            self.exits_path,
            ['state', 'highway', 'exit', 'latitude', 'longitude'],
            [['OK', 'I44', '283', '36.5679', '-95.2133']],
        )

        out = self._run_import()

        self.assertEqual(FuelStation.objects.filter(opis_id=7).count(), 1)
        station = FuelStation.objects.get(opis_id=7)
        self.assertEqual(float(station.price_per_gallon), 3.10)
        self.assertIn('Merged 2 duplicate rows', out)

    def test_address_with_no_exit_number_uses_city_centroid(self):
        _write_csv(
            self.csv_path,
            ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID',
             'Retail Price'],
            [['7', 'WOODSHED', 'I-44, Big Cabin', 'Big Cabin', 'OK', '307', '3.00']],
        )
        _write_csv(
            self.exits_path,
            ['state', 'highway', 'exit', 'latitude', 'longitude'],
            [['OK', 'I44', '283', '36.5679', '-95.2133']],
        )

        self._run_import()

        station = FuelStation.objects.get(opis_id=7)
        self.assertEqual(station.geocode_precision, 'city')
