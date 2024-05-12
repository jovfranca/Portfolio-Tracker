from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from django.conf import settings

from .historical_data import HistoricalData

class Portfolio(models.Model):
    description= models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete= models.CASCADE, related_name= 'portfolios')
    historical_data = GenericRelation(HistoricalData)

    def __str__(self):
        return f"{self.description} de {self.user.name}"