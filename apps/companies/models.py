import zoneinfo

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify

hex_color = RegexValidator(r'^#[0-9a-fA-F]{6}$', 'أدخل لوناً بصيغة ‎#RRGGBB.')


class Company(models.Model):
    """A tenant: one business whose social media Wakeel runs.

    Everything else (plans, posts, media, jobs) hangs off a company, and every
    query in the app is scoped to the company the user is currently working in.
    """

    class ContentLanguage(models.TextChoices):
        AR_MSA = 'ar_msa', 'العربية الفصحى'
        AR_LOCAL = 'ar_local', 'العربية بلهجة السوق المحلي'
        EN = 'en', 'الإنجليزية'
        AR_EN = 'ar_en', 'العربية والإنجليزية معاً'

    class Tone(models.TextChoices):
        PROFESSIONAL = 'professional', 'مهنية وموثوقة'
        FRIENDLY = 'friendly', 'ودودة وقريبة'
        BOLD = 'bold', 'جريئة وحماسية'
        LUXURY = 'luxury', 'فاخرة وراقية'
        PLAYFUL = 'playful', 'مرحة وخفيفة'
        INSPIRING = 'inspiring', 'ملهمة وتحفيزية'

    class Font(models.TextChoices):
        CAIRO = 'cairo', 'Cairo'
        TAJAWAL = 'tajawal', 'Tajawal'
        ALMARAI = 'almarai', 'Almarai'
        PLEX = 'plex', 'IBM Plex Sans Arabic'
        READEX = 'readex', 'Readex Pro'
        MESSIRI = 'messiri', 'El Messiri'
        KUFI = 'kufi', 'Noto Kufi Arabic'
        AMIRI = 'amiri', 'Amiri'

    TIMEZONE_CHOICES = [
        ('Africa/Khartoum', 'الخرطوم (GMT+2)'),
        ('Asia/Qatar', 'الدوحة (GMT+3)'),
        ('Asia/Riyadh', 'الرياض (GMT+3)'),
        ('Asia/Dubai', 'دبي (GMT+4)'),
        ('Africa/Cairo', 'القاهرة'),
        ('Asia/Kuwait', 'الكويت (GMT+3)'),
        ('Asia/Muscat', 'مسقط (GMT+4)'),
        ('Asia/Bahrain', 'المنامة (GMT+3)'),
        ('Asia/Amman', 'عمّان'),
        ('Europe/London', 'لندن'),
    ]

    name = models.CharField('اسم الشركة', max_length=150)
    slug = models.SlugField(max_length=170, unique=True, allow_unicode=True)
    logo = models.ImageField('الشعار', upload_to='logos/', blank=True)

    # About the business
    industry = models.CharField('المجال', max_length=150)
    country = models.CharField('الدولة', max_length=80)
    city = models.CharField('المدينة', max_length=80, blank=True)
    description = models.TextField('نبذة عن الشركة', help_text='ماذا تقدم الشركة، ولمن، وما الذي يميزها.')
    products = models.TextField('المنتجات والخدمات', blank=True)
    usp = models.TextField('نقاط التميز', blank=True, help_text='لماذا يختار العميل هذه الشركة دون منافسيها؟')
    target_audience = models.TextField('الجمهور المستهدف', blank=True)
    competitors = models.TextField('المنافسون', blank=True)
    goals = models.TextField('أهداف التسويق', blank=True, help_text='مثل: زيادة الوعي، جلب عملاء محتملين، زيادة المبيعات.')

    # Voice
    content_language = models.CharField('لغة المحتوى', max_length=10, choices=ContentLanguage.choices, default=ContentLanguage.AR_MSA)
    tone = models.CharField('نبرة الخطاب', max_length=20, choices=Tone.choices, default=Tone.PROFESSIONAL)
    voice_notes = models.TextField('ملاحظات على الأسلوب', blank=True, help_text='عبارات مفضلة، أو أسلوب معين في الكتابة.')
    dos = models.TextField('ما يجب فعله', blank=True)
    donts = models.TextField('ما يجب تجنبه', blank=True)
    brand_hashtags = models.CharField('وسوم العلامة', max_length=300, blank=True, help_text='تُضاف إلى المنشورات عند الحاجة، مفصولة بمسافات.')

    # Visual identity
    primary_color = models.CharField('اللون الأساسي', max_length=7, default='#4F46E5', validators=[hex_color])
    secondary_color = models.CharField('اللون الثانوي', max_length=7, default='#0EA5E9', validators=[hex_color])
    accent_color = models.CharField('لون التمييز', max_length=7, default='#F59E0B', validators=[hex_color])
    heading_font = models.CharField('خط العناوين', max_length=20, choices=Font.choices, default=Font.CAIRO)
    body_font = models.CharField('خط النصوص', max_length=20, choices=Font.choices, default=Font.TAJAWAL)

    # Contact details printed on designs and used in calls to action
    website = models.CharField('الموقع الإلكتروني', max_length=200, blank=True)
    phone = models.CharField('رقم التواصل', max_length=30, blank=True)
    whatsapp = models.CharField('واتساب', max_length=30, blank=True)
    facebook_page = models.CharField('صفحة فيسبوك', max_length=200, blank=True)
    instagram_handle = models.CharField('حساب إنستغرام', max_length=100, blank=True)
    tiktok_handle = models.CharField('حساب تيك توك', max_length=100, blank=True)

    timezone = models.CharField('المنطقة الزمنية', max_length=50, choices=TIMEZONE_CHOICES, default='Asia/Qatar')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'شركة'
        verbose_name_plural = 'الشركات'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True) or 'company'
            slug, n = base, 2
            while Company.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def tzinfo(self):
        return zoneinfo.ZoneInfo(self.timezone)

    @property
    def initials(self):
        # Two Arabic letters join into a readable mark; a lone one (e.g. «إ») can look like punctuation.
        name = self.name.strip()
        return name[:2] if name[:1] and '\u0600' <= name[0] <= '\u06ff' else (name[:1] or '؟').upper()


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'المالك'
        ADMIN = 'admin', 'مدير'
        EDITOR = 'editor', 'محرر محتوى'
        VIEWER = 'viewer', 'مشاهد'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField('الدور', max_length=10, choices=Role.choices, default=Role.EDITOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'عضوية'
        verbose_name_plural = 'العضويات'
        constraints = [models.UniqueConstraint(fields=['company', 'user'], name='unique_company_member')]

    def __str__(self):
        return f'{self.user} @ {self.company} ({self.get_role_display()})'

    # Owners and admins run the company: brand kit, team, approvals.
    @property
    def can_manage(self):
        return self.role in (self.Role.OWNER, self.Role.ADMIN)

    @property
    def can_edit(self):
        return self.role != self.Role.VIEWER


class MediaAsset(models.Model):
    """A photo in the company's media library, usable as a design background."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='assets')
    file = models.ImageField('الصورة', upload_to='assets/%Y/%m/', width_field='width', height_field='height')
    title = models.CharField('الوصف', max_length=150, blank=True)
    tags = models.CharField('الوسوم', max_length=200, blank=True, help_text='كلمات تساعد في اختيار الصورة المناسبة للمنشور.')
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'صورة'
        verbose_name_plural = 'مكتبة الوسائط'
        ordering = ['-created_at']

    def __str__(self):
        return self.title or self.file.name
