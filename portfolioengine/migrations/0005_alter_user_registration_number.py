# Generated by Django 5.0.6 on 2024-05-11 20:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portfolioengine', '0004_allocationclass_broker_country_asset_position_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='registration_number',
            field=models.PositiveIntegerField(null=True),
        ),
    ]
