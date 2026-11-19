"""Which operator serves a company (the operating model of Enjaz, package enjaz-operators). Enjaz develops Wakeel; an
operator offers it to each company, chosen from the company's country. The operator's name, legal details, contact
address and payment gateway follow the company everywhere in the app."""
from enjaz_operators import countries, registry

PRODUCT = 'wakeel'

# Country names as companies write them -> ISO 3166 codes (the names in the 16 languages are matched too).
COMMON_NAMES = {
    'المملكة العربية السعودية': 'SA', 'السعودية': 'SA', 'الإمارات': 'AE', 'الامارات': 'AE', 'uae': 'AE',
    'الأردن': 'JO', 'الاردن': 'JO', 'عمان': 'OM', 'عُمان': 'OM', 'مصر': 'EG', 'السودان': 'SD', 'قطر': 'QA',
    'الكويت': 'KW', 'البحرين': 'BH',
}


def code_from_name(text):
    """ISO code of a country written as free text in any of the app's languages; '' when unknown."""
    text = (text or '').strip()
    if not text:
        return ''
    if countries.is_country(text) and len(text) == 2:
        return text.upper()
    key = text.casefold()
    for name, code in COMMON_NAMES.items():
        if key == name.casefold():
            return code
    data = countries._data()
    for code, names in data.items():
        if key in (n.casefold() for n in names.values()):
            return code
    return ''


def of_company(company):
    """registry.Operator of the company (the product's default for a company without one)."""
    if company is not None and company.operator:
        try:
            return registry.get(PRODUCT, company.operator)
        except registry.RegistryError:
            pass
    return registry.default(PRODUCT)


def of_request(request):
    """ENJAZ_OPERATORS["ACCOUNT"]: the operator key of the company the user works in, or None for a visitor."""
    company = getattr(request, 'company', None)
    return of_company(company).key if company is not None else None


def assign(company, country_code):
    """Keep the company's country code and the operator that serves it there (not saved here)."""
    company.country_code = (country_code or '').upper()
    company.operator = registry.for_country(PRODUCT, company.country_code).key
