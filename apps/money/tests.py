from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.companies.models import Company

from . import currencies, rates
from .models import ExchangeRate, RateLog


class CurrencyTests(TestCase):
    def test_currency_of_a_country(self):
        self.assertEqual(currencies.for_country('QA'), 'QAR')
        self.assertEqual(currencies.for_country('sd'), 'SDG')
        self.assertEqual(currencies.for_country('JP'), 'JPY')
        self.assertEqual(currencies.for_country(''), 'USD')
        self.assertEqual(currencies.for_country('ZZ'), 'USD')

    def test_smallest_unit(self):
        self.assertEqual(currencies.quantize('36.4', 'QAR'), Decimal('36.40'))
        self.assertEqual(currencies.quantize('1.2345', 'KWD'), Decimal('1.235'))
        self.assertEqual(currencies.quantize('1592.5', 'JPY'), Decimal('1593'))
        self.assertEqual(currencies.to_minor('36.40', 'QAR'), 3640)
        self.assertEqual(currencies.to_minor('1.5', 'KWD'), 1500)

    def test_written_in_the_language(self):
        self.assertIn('ر.ق', currencies.format('36.4', 'QAR', 'ar'))
        self.assertIn('36.40', currencies.format('36.4', 'QAR', 'en'))

    def test_company_takes_its_country_currency(self):
        company = Company.objects.create(name='Doha Co', industry='x', country='قطر', description='x')
        self.assertEqual(company.currency, 'QAR')
        company.country = 'Sudan'
        company.save()
        self.assertEqual(Company.objects.get(pk=company.pk).currency, 'QAR')      # only the console changes it


class RateTests(TestCase):
    def test_pegs_are_exact(self):
        rate = rates.get('QAR')
        self.assertEqual(rate.source, 'peg')
        self.assertEqual([rate.from_usd(u) for u in (10, 25, 50, 100)],
                         [Decimal('36.40'), Decimal('91.00'), Decimal('182.00'), Decimal('364.00')])
        self.assertEqual(rate.from_points(120), Decimal('0.44'))                  # $0.12 -> 0.4368 -> 0.44

    def test_no_rate_means_nothing_sold(self):
        with self.assertRaises(rates.RateUnavailable):
            rates.get('EGP')

    def test_sources_that_agree_set_the_rate(self):
        updated, disputed = rates.settle({'a': {'EGP': Decimal('54.20'), 'QAR': Decimal('3.65')},
                                          'b': {'EGP': Decimal('54.40')}})
        self.assertEqual((updated, disputed), (['EGP'], []))                      # the peg is never overwritten
        self.assertEqual(rates.get('EGP').per_usd, Decimal('54.20'))
        self.assertEqual(rates.get('QAR').per_usd, Decimal('3.64'))
        self.assertEqual(RateLog.objects.filter(currency='EGP').count(), 1)

    def test_sources_that_disagree_set_nothing(self):
        updated, disputed = rates.settle({'a': {'SDG': Decimal('449.7')}, 'b': {'SDG': Decimal('600.2')}})
        self.assertEqual((updated, disputed), ([], ['SDG']))
        with self.assertRaises(rates.RateUnavailable):
            rates.get('SDG')

    def test_one_source_may_not_jump(self):
        rates.settle({'a': {'EGP': Decimal('50')}})
        self.assertEqual(rates.settle({'a': {'EGP': Decimal('60')}}), ([], ['EGP']))
        self.assertEqual(rates.settle({'a': {'EGP': Decimal('52')}}), (['EGP'], []))

    def test_automatic_rate_goes_stale(self):
        rates.settle({'a': {'EGP': Decimal('54')}}, now=timezone.now() - rates.AUTO_MAX_AGE - timedelta(minutes=1))
        with self.assertRaises(rates.RateUnavailable):
            rates.get('EGP')

    def test_manual_rate_holds_then_expires(self):
        rates.set_manual('SDG', '2500', hours=3, note='market, Khartoum')
        rate = rates.get('SDG')
        self.assertEqual((rate.source, rate.from_usd(10)), ('manual', Decimal('25000.00')))
        rates.settle({'a': {'SDG': Decimal('600')}, 'b': {'SDG': Decimal('600')}})
        self.assertEqual(rates.get('SDG').per_usd, Decimal('2500'))               # the automatic update leaves it alone
        with self.assertRaises(rates.RateUnavailable):
            rates.get('SDG', now=timezone.now() + timedelta(hours=3, minutes=1))
        with self.assertRaises(ValueError):
            rates.set_manual('QAR', '3.7', hours=1)                               # a peg is not set by hand

    def test_command(self):
        found = {'open.er-api.com': {'EGP': Decimal('54.2')}, 'currency-api': {'EGP': Decimal('54.19')}}
        with mock.patch('apps.money.sources.fetch_all', return_value=found):
            call_command('update_exchange_rates', stdout=mock.MagicMock())
        self.assertEqual(ExchangeRate.objects.get(currency='EGP').source, ExchangeRate.API)
