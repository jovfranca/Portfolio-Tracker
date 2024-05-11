from django.db import models

class AllocationClass(models.Model):
    description = models.CharField(max_length=100)
