import io
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.companies.models import Company, MediaAsset, Membership
from apps.content.models import ContentPlan, Post

MEDIA = tempfile.mkdtemp()
def _png():
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), '#6d5ef8').save(buf, 'PNG')
    return buf.getvalue()


PNG = _png()


@override_settings(MEDIA_ROOT=MEDIA)
class DeletionTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.company = Company.objects.create(name='إنجاز', industry='برمجيات', country='السودان', description='و')
        self.owner = User.objects.create_user(username='o@x.test', email='o@x.test', password='Strong-pass-123')
        self.editor = User.objects.create_user(username='e@x.test', email='e@x.test', password='Strong-pass-123')
        Membership.objects.create(company=self.company, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(company=self.company, user=self.editor, role=Membership.Role.EDITOR)
        plan = ContentPlan.objects.create(company=self.company, month='2026-10-01', platforms=['facebook'])
        self.post = Post.objects.create(company=self.company, plan=plan, title='م', platforms=['facebook'])
        self.post.image.save('p.png', ContentFile(PNG))
        self.asset = MediaAsset.objects.create(company=self.company, file=SimpleUploadedFile('a.png', PNG, 'image/png'))
        self.files = [self.post.image, self.asset.file]

    def assertFilesGone(self):
        for f in self.files:
            self.assertFalse(f.storage.exists(f.name), f.name)

    def test_owner_deletes_company_with_everything(self):
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse('companies:delete'), {'confirm_name': 'إنجاز'})
        self.assertRedirects(r, reverse('core:dashboard'), fetch_redirect_response=False)
        self.assertFalse(Company.objects.exists())
        self.assertFalse(Post.objects.exists())
        self.assertFalse(ContentPlan.objects.exists())
        self.assertFilesGone()

    def test_company_delete_needs_exact_name_and_owner(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('companies:delete'), {'confirm_name': 'اسم خطأ'})
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(reverse('companies:delete'), {'confirm_name': 'إنجاز'}).status_code, 403)
        self.assertTrue(Company.objects.exists())

    def test_editor_leaves_owner_cannot(self):
        self.client.force_login(self.editor)
        self.client.post(reverse('companies:leave'))
        self.assertFalse(Membership.objects.filter(user=self.editor).exists())
        self.client.force_login(self.owner)
        self.client.post(reverse('companies:leave'))
        self.assertTrue(Membership.objects.filter(user=self.owner).exists())

    def test_bulk_delete_posts(self):
        other = Post.objects.create(company=Company.objects.create(name='غير', industry='x', country='y', description='z'),
                                    title='لا', platforms=['facebook'])
        self.client.force_login(self.editor)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse('api:posts_bulk_delete'), {'ids': [self.post.pk, other.pk]}, content_type='application/json')
        self.assertEqual(r.json()['deleted'], 1)
        self.assertTrue(Post.objects.filter(pk=other.pk).exists())
        self.assertFalse(self.post.image.storage.exists(self.post.image.name))

    def test_account_delete_requires_password_and_removes_owned_companies(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('accounts:delete'), {'password': 'wrong'})
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('accounts:delete'), {'password': 'Strong-pass-123'})
        self.assertFalse(User.objects.filter(pk=self.owner.pk).exists())
        self.assertFalse(Company.objects.exists())
        self.assertTrue(User.objects.filter(pk=self.editor.pk).exists())
        self.assertFilesGone()
