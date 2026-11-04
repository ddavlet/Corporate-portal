from django.db import migrations, models

PAYMENT_TYPE_CHOICES = [
    ("Наличные", "Наличные"),
    ("Перечисление", "Перечисление"),
    ("Пополнение", "Пополнение"),
    ("Платежная карта", "Платежная карта"),
    ("Начисление ЗП", "Начисление ЗП"),
    ("Инвест. наличные", "Инвест. наличные"),
    ("Инвест. перечисление", "Инвест. перечисление"),
]


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0066_remove_unused_cross_tenant_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='request',
            name='payment_type',
            field=models.CharField(choices=PAYMENT_TYPE_CHOICES, default='Наличные', max_length=50),
        ),
        migrations.AlterField(
            model_name='requestformpaymenttypeconfig',
            name='payment_type',
            field=models.CharField(choices=PAYMENT_TYPE_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name='requestapprovalpaymenttypeconfig',
            name='payment_type',
            field=models.CharField(choices=PAYMENT_TYPE_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name='autorequesttemplate',
            name='payment_type',
            field=models.CharField(choices=PAYMENT_TYPE_CHOICES, max_length=50),
        ),
    ]
