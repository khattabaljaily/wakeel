from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations

RATE = Decimal('3.64')      # the Qatar Central Bank's fixed rate: what a dollar of balance is worth in riyals


def _scale(value, factor):
    return int((Decimal(value) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def convert(factor):
    def run(apps, schema_editor):
        Wallet = apps.get_model('credits', 'Wallet')
        Transaction = apps.get_model('credits', 'WalletTransaction')
        for wallet in Wallet.objects.exclude(balance=0):
            wallet.balance = _scale(wallet.balance, factor)
            wallet.save(update_fields=['balance'])
        for txn in Transaction.objects.all().iterator():
            txn.delta = _scale(txn.delta, factor)
            for line in txn.breakdown or []:
                line['points'] = _scale(line.get('points', 0), factor)
            txn.save(update_fields=['delta', 'breakdown'])
    return run


class Migration(migrations.Migration):
    """The wallet was kept in points of 0.001 dollar; it is kept in points of 0.001 riyal now (owner's decision, 2026-11-25:
    the riyal is the base currency). Every balance, ledger line and itemised line is worth the same as before."""
    dependencies = [('credits', '0001_initial')]
    operations = [migrations.RunPython(convert(RATE), convert(1 / RATE))]
