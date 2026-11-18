"""Security review 2026-11-19: the outside-client role sees nothing of the company's papers, team, marketing or inbox. Every page is
closed to it unless it says `client=True` (the dashboard and the personal notes)."""
from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from apps.companies.models import Membership
from apps.content.tests import make_company, make_user
from apps.library.models import Record
from apps.library.tests import PDF


class ClientRole(TestCase):
    def setUp(self):
        self.company = make_company('Alpha')
        self.owner = make_user('o@example.com', self.company)
        self.viewer = make_user('v@example.com', self.company, Membership.Role.VIEWER)
        self.outsider = make_user('c@example.com', self.company, Membership.Role.CLIENT)
        self.record = Record(company=self.company, title='Licence', category='company', content_type='application/pdf')
        self.record.file.save('l.pdf', ContentFile(PDF), save=False)
        self.record.save()
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'

    def get(self, user, name, *args):
        self.client.force_login(user)
        return self.client.get(reverse(name, args=args))

    def test_the_papers_their_files_and_what_the_ai_made_of_them_are_closed_to_a_client(self):
        for name, args in (('library:list', ()), ('library:file', (self.record.pk,)), ('documents:issued', ()), ('documents:templates', ()),
                           ('docops:result', (1,)), ('companies:team', ()), ('companies:media', ()), ('content:plan_list', ()),
                           ('content:post_list', ()), ('content:calendar', ()), ('insights:dashboard', ()), ('inbox:inbox', ()),
                           ('ads:list', ()), ('mail:home', ()), ('forms:list', ()), ('sharing:list', ())):
            try:
                response = self.get(self.outsider, name, *args)
            except NoReverseMatch:
                self.fail(f'unknown route {name}')
            self.assertEqual(response.status_code, 403, name)

    def test_the_same_pages_still_open_for_a_viewer(self):
        for name, args in (('library:list', ()), ('library:file', (self.record.pk,)), ('documents:issued', ()), ('companies:team', ()),
                           ('content:post_list', ())):
            self.assertEqual(self.get(self.viewer, name, *args).status_code, 200, name)

    def test_what_a_client_uses_stays_open(self):
        self.assertEqual(self.get(self.outsider, 'core:dashboard').status_code, 200)
        self.assertEqual(self.get(self.outsider, 'notes:list').status_code, 200)
        self.assertEqual(self.get(self.outsider, 'notifications:list').status_code, 200)

    def test_a_client_cannot_read_a_job_result_of_the_company(self):
        from apps.jobs.models import Job
        job = Job.objects.create(company=self.company, kind=Job.Kind.CALL, params={'result': {'legal_name': 'secret'}}, created_by=self.owner)
        self.client.force_login(self.outsider)
        self.assertGreaterEqual(self.client.get(reverse('api:job_detail', args=[job.pk])).status_code, 400)
