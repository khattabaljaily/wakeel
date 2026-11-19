import json

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core import filecrypto
from apps.core.tenancy import CompanyScopedModel

RTL_LANGUAGES = ('ar', 'fa')


class Document(CompanyScopedModel):
    """A letter or a certificate written for the company: typed by a member, or written by the AI from instructions."""

    LETTER = 'letter'
    CERTIFICATE = 'certificate'
    GENERAL = 'document'          # any other paper: a contract, a form, a minute, a quotation...
    KINDS = [(LETTER, _('Letter')), (CERTIFICATE, _('Certificate')), (GENERAL, _('Other document'))]
    # Where it is kept in the library (the same folders as the uploaded papers); chosen when it is made.
    DEFAULT_CATEGORY = {LETTER: 'letters', CERTIFICATE: 'letters', GENERAL: 'letters'}

    kind = models.CharField(max_length=12, choices=KINDS, default=LETTER)
    category = models.CharField(_('category'), max_length=20, default='letters')
    doc_type = models.CharField(_('document type'), max_length=200, blank=True)   # "Experience certificate": free text
    title = models.CharField(_('title'), max_length=200)
    recipient = models.CharField(_('to'), max_length=200, blank=True)
    language = models.CharField(_('language'), max_length=8, choices=settings.LANGUAGES, default='en')
    doc_date = models.DateField(_('date'), default=timezone.localdate)
    # The product keeps no stamp or signature: a document that must be checked carries a QR that opens it (see verify.py).
    include_qr = models.BooleanField(_('add a verification QR code'), default=False, help_text=_(
        'Whoever holds the printed paper can scan it and see the original document, to compare the two.'))
    written_by_ai = models.BooleanField(default=False, editable=False)
    # What the QR opens: /v/<code>/. Made the first time it is needed.
    verify_code = models.CharField(max_length=24, unique=True, null=True, blank=True, editable=False)
    # The approval of the document (the company setting `documents_need_approval`): 'approved' unless one is needed.
    DRAFT, PENDING, APPROVED, REJECTED = 'draft', 'pending', 'approved', 'rejected'
    STATUSES = [(DRAFT, _('Draft')), (PENDING, _('Waiting for approval')), (APPROVED, _('Approved')), (REJECTED, _('Rejected'))]
    status = models.CharField(max_length=10, choices=STATUSES, default=APPROVED, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+', editable=False)
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    review_note = models.CharField(max_length=300, blank=True, editable=False)
    # Set when the owner or an admin cancels the document: its public verification page then says so.
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title

    # Words that already make "to" unnecessary in front of an addressee ("Dear", "To", "السادة", "إلى"...).
    ADDRESSED_ALREADY = ('to ', 'dear ', 'attn', 'إلى', 'الى', 'السادة', 'السيد', 'السيدة', 'الأستاذ', 'الاستاذ', 'لدى', 'عناية')

    @property
    def addressed_to(self):
        """The addressee as printed above the text: "من يهمه الأمر" becomes "إلى من يهمه الأمر"."""
        name = (self.recipient or '').strip()
        if not name or name.casefold().startswith(self.ADDRESSED_ALREADY):
            return name
        from django.utils.translation import gettext
        return gettext('To %(name)s') % {'name': name}

    @property
    def category_label(self):
        from apps.library.models import Record
        return dict(Record.CATEGORIES).get(self.category, '')

    # --- The text of the document: kept apart and encrypted (see DocumentContent), never in this table -------------

    def _load_content(self):
        if not hasattr(self, '_content'):
            self._content = {'subject': '', 'body': '', 'design': '', 'values': {}}
            if self.pk:
                row = DocumentContent.all_companies.filter(document_id=self.pk).first()
                if row is not None:
                    self._content = row.read()
        return self._content

    @property
    def subject(self):
        return self._load_content()['subject']

    @subject.setter
    def subject(self, value):
        self._load_content()['subject'] = value or ''
        self._content_dirty = True

    @property
    def body(self):
        return self._load_content()['body']

    @body.setter
    def body(self, value):
        self._load_content()['body'] = value or ''
        self._content_dirty = True

    # A designed document (the page is HTML made by the AI): the safe HTML with its {{blanks}}, and the value of each.
    @property
    def design(self):
        return self._load_content().get('design', '')

    @design.setter
    def design(self, value):
        from .safehtml import clean_html
        self._load_content()['design'] = clean_html(value or '')           # always safe, whoever sets it
        self._content_dirty = True

    @property
    def values(self):
        return self._load_content().get('values') or {}

    @values.setter
    def values(self, value):
        self._load_content()['values'] = dict(value or {})
        self._content_dirty = True

    @property
    def is_designed(self):
        return bool(self.design)

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self.__dict__.pop('_content', None)            # the sealed text is read again from its own table
        self._content_dirty = False

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if getattr(self, '_content_dirty', False):
            DocumentContent.store(self, self._content)
            self._content_dirty = False

    @property
    def is_rtl(self):
        return self.language in RTL_LANGUAGES

    @property
    def is_approved(self):
        return self.status == self.APPROVED

    @property
    def is_verifiable(self):
        return self.include_qr

    def ensure_code(self):
        if not self.verify_code:
            import secrets
            self.verify_code = secrets.token_urlsafe(12)
            self.save(update_fields=['verify_code'])
        return self.verify_code


class DocumentTemplate(CompanyScopedModel):
    """A letter or certificate kept to be used again. The subject and the text may hold blanks written {{like this}}:
    using the template asks for each blank once and makes a new document. A template never carries the verification QR:
    a document made from it starts without it."""

    kind = models.CharField(max_length=12, choices=Document.KINDS, default=Document.LETTER)
    name = models.CharField(_('template name'), max_length=200)
    category = models.CharField(_('category'), max_length=20, default='letters')
    # A designed template: the page as safe HTML/CSS with {{blanks}} (see safehtml.py). Empty: a text template (subject, body).
    html = models.TextField(blank=True, editable=False)
    key = models.CharField(max_length=200, editable=False, db_index=True, default='')      # the name, normalised: one template per type
    recipient = models.CharField(max_length=200, blank=True)
    subject = models.CharField(max_length=300, blank=True)
    body = models.TextField(blank=True)
    language = models.CharField(max_length=8, choices=settings.LANGUAGES, default='en')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'id']
        constraints = [models.UniqueConstraint(fields=['company', 'key', 'language'], name='one_template_per_type_and_language')]

    def __str__(self):
        return self.name

    @property
    def category_label(self):
        from apps.library.models import Record
        return dict(Record.CATEGORIES).get(self.category, '')

    @property
    def is_designed(self):
        return bool(self.html)

    @staticmethod
    def make_key(name):
        """'  Experience   Certificate ' and 'experience certificate' are the same type."""
        return ' '.join((name or '').split()).casefold()[:200]

    def save(self, *args, **kwargs):
        from .safehtml import clean_html
        self.key = self.make_key(self.name)
        self.html = clean_html(self.html)                                    # a design is stored only in its safe form
        super().save(*args, **kwargs)


class DocumentContent(CompanyScopedModel):
    """The subject and the text of one document, sealed with the company's key (AES-256-GCM, like the private files).
    They are read only when a member opens, edits or prints the document, never to build a list or a preview."""

    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name='sealed_content')
    payload = models.BinaryField()

    @staticmethod
    def seal(company_id, content):
        """`content` is a dict: subject, body, and for a designed document its design and values."""
        raw = json.dumps(content, ensure_ascii=False).encode()
        return filecrypto.encrypt(settings.FILE_ENCRYPTION_KEY, company_id, raw)

    def read(self):
        data = json.loads(filecrypto.decrypt(settings.FILE_ENCRYPTION_KEY, self.company_id, bytes(self.payload)))
        return {'subject': data.get('subject', ''), 'body': data.get('body', ''), 'design': data.get('design', ''),
                'values': data.get('values') or {}}

    @classmethod
    def store(cls, document, content):
        cls.all_companies.update_or_create(document=document, defaults={
            'company_id': document.company_id, 'payload': cls.seal(document.company_id, content)})
