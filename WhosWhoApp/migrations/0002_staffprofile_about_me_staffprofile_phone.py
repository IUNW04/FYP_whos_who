# Generated by Django 4.2.3 on 2025-01-19 05:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('WhosWhoApp', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffprofile',
            name='about_me',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='staffprofile',
            name='phone',
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
