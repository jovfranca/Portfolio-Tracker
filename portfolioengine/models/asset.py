from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from .historical_data import AssetData

class Asset(models.Model):
    ticker = models.CharField(max_length=100)
    description = models.CharField(max_length=100)
    country = models.ForeignKey("Country", on_delete=models.CASCADE, related_name='assets')
    historical_data = GenericRelation(AssetData)
