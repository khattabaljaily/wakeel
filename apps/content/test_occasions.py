import datetime
from unittest import mock

from django.test import TestCase

from apps.ai import planner
from apps.ai.client import AIResult

from .models import ContentPlan
from .occasions import between, in_month
from .tests import PLAN_DATA, make_company


class OccasionTests(TestCase):
    def names(self, company, start, end):
        return {(o['date'], o['name']) for o in between(company, start, end)}

    def test_national_days_follow_the_country(self):
        qatar = make_company('ق', country='قطر', timezone='Asia/Qatar')
        sudan = make_company('س', country='السودان', timezone='Africa/Khartoum')
        dec = (datetime.date(2026, 12, 1), datetime.date(2027, 1, 1))
        self.assertIn((datetime.date(2026, 12, 18), 'اليوم الوطني القطري'), self.names(qatar, *dec))
        self.assertNotIn((datetime.date(2026, 12, 18), 'اليوم الوطني القطري'), self.names(sudan, *dec))
        self.assertIn((datetime.date(2027, 1, 1), 'عيد استقلال السودان'), self.names(sudan, *dec))

    def test_country_text_wins_over_timezone(self):
        # A Sudanese company that works on Doha time still gets Sudan's occasions.
        company = make_company('س', country='السودان', timezone='Asia/Qatar')
        self.assertIn('عيد استقلال السودان', {o['name'] for o in in_month(company, datetime.date(2027, 1, 1))})

    def test_islamic_dates_are_computed_and_marked_approximate(self):
        company = make_company('ق', country='قطر')
        eid = [o for o in in_month(company, datetime.date(2027, 3, 1)) if o['name'] == 'عيد الفطر']
        self.assertEqual(eid[0]['date'], datetime.date(2027, 3, 9))
        self.assertTrue(eid[0]['approx'])

    def test_non_arab_market_gets_no_islamic_or_arab_days(self):
        company = make_company('ل', country='المملكة المتحدة', timezone='Europe/London')
        names = {o['name'] for o in between(company, datetime.date(2027, 1, 1), datetime.date(2027, 12, 31))}
        self.assertNotIn('عيد الفطر', names)
        self.assertNotIn('عيد الأم', names)
        self.assertIn('رأس السنة الميلادية', names)

    @mock.patch('apps.ai.planner.call_json', return_value=AIResult(data=PLAN_DATA))
    def test_planner_prompt_lists_the_months_occasions(self, call_json):
        company = make_company('ق', country='قطر')
        plan = ContentPlan.objects.create(company=company, month=datetime.date(2026, 12, 1), platforms=['facebook'])
        planner.generate_plan(plan)
        prompt = call_json.call_args.args[1]
        self.assertIn('2026-12-18: اليوم الوطني القطري', prompt)
