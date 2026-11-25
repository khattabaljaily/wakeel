"""Which currency a country pays in, how many decimals it has and how an amount in it is written, for every country
(the data is Babel's, from the Unicode CLDR). Nothing here touches the database."""
from decimal import ROUND_HALF_UP, Decimal

from babel import numbers

USD = 'USD'

# Currencies fixed to the dollar by their central bank: the official rate, never a market quote.
PEGS = {
    'QAR': Decimal('3.64'),      # Qatar Central Bank
    'SAR': Decimal('3.75'),      # Saudi Central Bank
    'AED': Decimal('3.6725'),    # Central Bank of the UAE
    'BHD': Decimal('0.376'),     # Central Bank of Bahrain
    'OMR': Decimal('0.3845'),    # Central Bank of Oman
    'JOD': Decimal('0.709'),     # Central Bank of Jordan
}


def is_known(code):
    return bool(code) and numbers.is_currency(code.upper())


def for_country(country_code):
    """The legal tender of a country (ISO 3166 code); USD when the country is unknown or has none."""
    if not country_code:
        return USD
    try:
        found = numbers.get_territory_currencies(country_code.upper(), tender=True, non_tender=False)
    except Exception:            # an unknown territory
        return USD
    return found[0] if found else USD


def digits(code):
    """Decimal places the currency is written with: QAR 2, KWD 3, JPY 0."""
    return numbers.get_currency_precision(code.upper())


def quantize(amount, code):
    """An amount rounded to the currency's smallest unit (half up)."""
    return Decimal(str(amount)).quantize(Decimal(1).scaleb(-digits(code)), rounding=ROUND_HALF_UP)


def to_minor(amount, code):
    """An amount in the currency's smallest unit, as payment gateways count it: 36.40 QAR -> 3640, 1.500 KWD -> 1500."""
    return int(quantize(amount, code).scaleb(digits(code)))


def format(amount, code, language='en'):
    """An amount as people of `language` write it: '‏36.40 ر.ق.‏' in Arabic, 'QAR 36.40' in English."""
    try:
        return numbers.format_currency(quantize(amount, code), code.upper(), locale=_locale(language),
                                       currency_digits=True)
    except Exception:
        return f'{quantize(amount, code):,} {code.upper()}'


def symbol(code, language='en'):
    return numbers.get_currency_symbol(code.upper(), locale=_locale(language))


def name(code, language='en'):
    return numbers.get_currency_name(code.upper(), locale=_locale(language))


def _locale(language):
    return (language or 'en').replace('-', '_')
