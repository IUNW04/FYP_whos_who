from django.contrib import admin
from .models import StaffProfile, Department

admin.site.register(StaffProfile)
admin.site.register(Department)
from django.db import models

class Skill(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name
