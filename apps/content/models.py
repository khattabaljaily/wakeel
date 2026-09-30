from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.companies.models import Company, MediaAsset


class Platform(models.TextChoices):
    FACEBOOK = 'facebook', 'فيسبوك'
    INSTAGRAM = 'instagram', 'إنستغرام'
    TIKTOK = 'tiktok', 'تيك توك'


PLATFORM_ICONS = {
    Platform.FACEBOOK: 'bi-facebook',
    Platform.INSTAGRAM: 'bi-instagram',
    Platform.TIKTOK: 'bi-tiktok',
}


class ContentPlan(models.Model):
    """A month of content: the strategy the AI wrote and the posts it planned."""

    class Status(models.TextChoices):
        GENERATING = 'generating', 'قيد الإعداد'
        READY = 'ready', 'جاهزة'
        FAILED = 'failed', 'تعذّر الإعداد'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='plans')
    month = models.DateField('الشهر', help_text='أول يوم في الشهر.')
    platforms = models.JSONField('المنصات', default=list)
    posts_per_week = models.PositiveSmallIntegerField('عدد المنشورات أسبوعياً', default=4)
    brief = models.TextField('توجيهات هذا الشهر', blank=True,
                             help_text='عروض، مناسبات، منتجات جديدة، أو أي شيء تريد التركيز عليه.')

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.GENERATING)
    title = models.CharField('العنوان', max_length=200, blank=True)
    summary = models.TextField('ملخص الاستراتيجية', blank=True)
    goals = models.JSONField('الأهداف', default=list, blank=True)
    pillars = models.JSONField('محاور المحتوى', default=list, blank=True)
    key_dates = models.JSONField('المناسبات', default=list, blank=True)
    error = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'خطة محتوى'
        verbose_name_plural = 'خطط المحتوى'
        ordering = ['-month', '-created_at']

    def __str__(self):
        return self.title or f'{self.company} — {self.month:%Y-%m}'

    def get_absolute_url(self):
        return reverse('content:plan_detail', args=[self.pk])


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'مسودة'
        REVIEW = 'review', 'بانتظار المراجعة'
        APPROVED = 'approved', 'معتمد'
        PUBLISHED = 'published', 'منشور'

    class Format(models.TextChoices):
        IMAGE = 'image', 'تصميم ثابت'
        REEL = 'reel', 'فيديو قصير (ريلز / تيك توك)'
        STORY = 'story', 'قصة (ستوري)'

    class Size(models.TextChoices):
        SQUARE = 'square', 'مربع 1:1'
        PORTRAIT = 'portrait', 'طولي 4:5'
        STORY = 'story', 'عمودي 9:16'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='posts')
    plan = models.ForeignKey(ContentPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name='posts')

    platforms = models.JSONField('المنصات', default=list)
    format = models.CharField('نوع المنشور', max_length=10, choices=Format.choices, default=Format.IMAGE)
    status = models.CharField('الحالة', max_length=10, choices=Status.choices, default=Status.DRAFT)
    scheduled_at = models.DateTimeField('موعد النشر', null=True, blank=True)

    title = models.CharField('الفكرة', max_length=200)
    pillar = models.CharField('المحور', max_length=100, blank=True)
    objective = models.CharField('الهدف', max_length=100, blank=True)

    # Copy
    caption = models.TextField('نص المنشور', blank=True)
    hashtags = models.CharField('الوسوم', max_length=500, blank=True)

    # Design
    headline = models.CharField('العنوان الرئيسي', max_length=160, blank=True)
    subheadline = models.CharField('العنوان الفرعي', max_length=260, blank=True)
    cta = models.CharField('عبارة الدعوة', max_length=80, blank=True)
    badge = models.CharField('الشارة', max_length=40, blank=True, help_text='نص قصير بارز مثل: جديد، خصم 20%.')
    template = models.CharField('القالب', max_length=20, default='bold')
    size = models.CharField('المقاس', max_length=10, choices=Size.choices, default=Size.SQUARE)
    background = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name='صورة الخلفية')
    visual_notes = models.TextField('وصف الصورة المقترحة', blank=True)
    image = models.ImageField('التصميم', upload_to='posts/%Y/%m/', blank=True)
    image_stale = models.BooleanField(default=True, help_text='The design changed since the image was last rendered.')

    # Video formats (reel / TikTok): the AI writes the script, the team shoots it.
    video_script = models.TextField('سيناريو الفيديو', blank=True)

    review_note = models.TextField('ملاحظات المراجعة', blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Fields that change what the rendered image looks like.
    DESIGN_FIELDS = ('headline', 'subheadline', 'cta', 'badge', 'template', 'size', 'background')

    class Meta:
        verbose_name = 'منشور'
        verbose_name_plural = 'المنشورات'
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
