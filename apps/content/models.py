from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, MediaAsset


class Platform(models.TextChoices):
    FACEBOOK = 'facebook', _('فيسبوك')
    INSTAGRAM = 'instagram', _('إنستغرام')
    TIKTOK = 'tiktok', _('تيك توك')


PLATFORM_ICONS = {
    Platform.FACEBOOK: 'bi-facebook',
    Platform.INSTAGRAM: 'bi-instagram',
    Platform.TIKTOK: 'bi-tiktok',
}


class ContentPlan(models.Model):
    """A month of content: the strategy the AI wrote and the posts it planned."""

    class Status(models.TextChoices):
        GENERATING = 'generating', _('قيد الإعداد')
        READY = 'ready', _('جاهزة')
        FAILED = 'failed', _('تعذّر الإعداد')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='plans')
    month = models.DateField(_('الشهر'), help_text=_('أول يوم في الشهر.'))
    platforms = models.JSONField(_('المنصات'), default=list)
    posts_per_week = models.PositiveSmallIntegerField(_('عدد المنشورات أسبوعياً'), default=4)
    brief = models.TextField(_('توجيهات هذا الشهر'), blank=True,
                             help_text=_('عروض، مناسبات، منتجات جديدة، أو أي شيء تريد التركيز عليه.'))

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.GENERATING)
    title = models.CharField(_('العنوان'), max_length=200, blank=True)
    summary = models.TextField(_('ملخص الاستراتيجية'), blank=True)
    goals = models.JSONField(_('الأهداف'), default=list, blank=True)
    pillars = models.JSONField(_('محاور المحتوى'), default=list, blank=True)
    key_dates = models.JSONField(_('المناسبات'), default=list, blank=True)
    error = models.TextField(blank=True)
    # Secret for the client review page (/review/<token>/); empty when the link is off.
    share_token = models.CharField(max_length=64, blank=True, db_index=True)
    autopilot = models.BooleanField(default=False, help_text='Prepared by the autopilot, not by a person.')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('خطة محتوى')
        verbose_name_plural = _('خطط المحتوى')
        ordering = ['-month', '-created_at']

    def __str__(self):
        return self.title or f'{self.company} — {self.month:%Y-%m}'

    def get_absolute_url(self):
        return reverse('content:plan_detail', args=[self.pk])


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('مسودة')
        REVIEW = 'review', _('بانتظار المراجعة')
        APPROVED = 'approved', _('معتمد')
        PUBLISHED = 'published', _('منشور')

    class Format(models.TextChoices):
        IMAGE = 'image', _('تصميم ثابت')
        REEL = 'reel', _('فيديو قصير (ريلز / تيك توك)')
        STORY = 'story', _('قصة (ستوري)')

    class Size(models.TextChoices):
        SQUARE = 'square', _('مربع 1:1')
        PORTRAIT = 'portrait', _('طولي 4:5')
        STORY = 'story', _('عمودي 9:16')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='posts')
    plan = models.ForeignKey(ContentPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name='posts')

    platforms = models.JSONField(_('المنصات'), default=list)
    format = models.CharField(_('نوع المنشور'), max_length=10, choices=Format.choices, default=Format.IMAGE)
    status = models.CharField(_('الحالة'), max_length=10, choices=Status.choices, default=Status.DRAFT)
    scheduled_at = models.DateTimeField(_('موعد النشر'), null=True, blank=True)

    title = models.CharField(_('الفكرة'), max_length=200)
    pillar = models.CharField(_('المحور'), max_length=100, blank=True)
    objective = models.CharField(_('الهدف'), max_length=100, blank=True)

    # Copy
    caption = models.TextField(_('نص المنشور'), blank=True)
    hashtags = models.CharField(_('الوسوم'), max_length=500, blank=True)

    # Design
    headline = models.CharField(_('العنوان الرئيسي'), max_length=160, blank=True)
    subheadline = models.CharField(_('العنوان الفرعي'), max_length=260, blank=True)
    cta = models.CharField(_('عبارة الدعوة'), max_length=80, blank=True)
    badge = models.CharField(_('الشارة'), max_length=40, blank=True, help_text=_('نص قصير بارز مثل: جديد، خصم 20%.'))
    template = models.CharField(_('القالب'), max_length=20, default='bold')
    scheme = models.CharField(_('نظام الألوان'), max_length=20, blank=True, help_text=_('فارغ = الافتراضي للقالب.'))
    motif = models.CharField(_('الزخرفة'), max_length=20, blank=True, help_text=_('فارغ = الافتراضية للقالب.'))
    variant = models.PositiveIntegerField(default=0, help_text='Seeds the small random differences between designs.')
    vectors = models.JSONField(_('الرسوم'), default=list, blank=True,
                               help_text='Up to three keys of apps.studio.vectors; empty = guessed from the text.')
    size = models.CharField(_('المقاس'), max_length=10, choices=Size.choices, default=Size.SQUARE)
    background = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name=_('صورة الخلفية'))
    visual_notes = models.TextField(_('وصف الصورة المقترحة'), blank=True)
    image = models.ImageField(_('التصميم'), upload_to='posts/%Y/%m/', blank=True)
    image_stale = models.BooleanField(default=True, help_text='The design changed since the image was last rendered.')

    # Video formats (reel / TikTok): the AI writes the script, the team shoots it.
    video_script = models.TextField(_('سيناريو الفيديو'), blank=True)

    review_note = models.TextField(_('ملاحظات المراجعة'), blank=True)
    # A post made from another one: a language/dialect version (`language` set) or an evergreen repost.
    source_post = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='copies')
    language = models.CharField(_('لغة النسخة'), max_length=12, blank=True)
    evergreen = models.BooleanField(_('محتوى دائم'), default=False,
                                    help_text=_('صالح لإعادة النشر بصياغة جديدة بعد مدة.'))
    published_at = models.DateTimeField(null=True, blank=True)
    # Direct publishing (apps.social): ids of the published posts per platform, and the last failure.
    external_ids = models.JSONField(default=dict, blank=True)
    publish_error = models.TextField(blank=True)
    publish_attempted_at = models.DateTimeField(null=True, blank=True,
                                                help_text='Set when auto-publishing picks the post, so it is tried once.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Fields that change what the rendered image looks like.
    DESIGN_FIELDS = ('headline', 'subheadline', 'cta', 'badge', 'template', 'scheme', 'motif', 'variant', 'vectors', 'size', 'background')

    class Meta:
        verbose_name = _('منشور')
        verbose_name_plural = _('المنشورات')
        ordering = ['scheduled_at', 'pk']
        indexes = [models.Index(fields=['company', 'scheduled_at'])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('content:post_edit', args=[self.pk])

    @property
    def is_video(self):
        return self.format == self.Format.REEL

    @property
    def platform_icons(self):
        return [(p, PLATFORM_ICONS.get(p, 'bi-globe'), Platform(p).label) for p in self.platforms if p in Platform.values]

    @property
    def full_caption(self):
        return '\n\n'.join(part for part in (self.caption.strip(), self.hashtags.strip()) if part)


class PostComment(models.Model):
    """A message in a post's review thread, from a team member or from the client through a share link."""

    class Kind(models.TextChoices):
        COMMENT = 'comment', _('تعليق')
        CHANGES = 'changes', _('طلب تعديل')
        APPROVAL = 'approval', _('اعتماد')

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    # Set instead of `user` when the client comments through a plan's share link.
    guest_name = models.CharField(max_length=80, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.COMMENT)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('تعليق')
        verbose_name_plural = _('التعليقات')
        ordering = ['created_at']

    def __str__(self):
        return f'{self.author_name}: {self.body[:40]}'

    @property
    def author_name(self):
        if self.user:
            return self.user.display_name
        return self.guest_name or _('العميل')

    @property
    def is_guest(self):
        return self.user_id is None


class LearningSignal(models.Model):
    """Feedback Wakeel learns the brand's taste from: the team's edits to AI-written text,
    change requests, rewrite instructions and the client's comments. Signals are distilled
    into Company.lessons before the next plan (apps.content.learning)."""

    class Kind(models.TextChoices):
        EDIT = 'edit', _('تعديل نص')
        CHANGES = 'changes', _('طلب تعديل')
        REWRITE = 'rewrite', _('طلب إعادة كتابة')
        COMMENT = 'comment', _('تعليق العميل')

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='learning_signals')
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    field = models.CharField(max_length=30, blank=True)
    before = models.TextField(blank=True)
    after = models.TextField(blank=True)
    note = models.TextField(blank=True)
    from_client = models.BooleanField(default=False)
    used = models.BooleanField(default=False, help_text='Already distilled into the lessons.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['company', 'used'])]

    def __str__(self):
        return f'{self.get_kind_display()} · {self.company}'
