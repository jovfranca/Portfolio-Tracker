from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class HistoricalData(models.Model):
    date = models.DateField()
    value = models.FloatField()
    realized_gain = models.FloatField()
    unrealized_gain = models.FloatField()
    total_gain = models.FloatField()
    daily_profitability = models.FloatField()
    accumulated_profitability = models.FloatField()
    
    content_type = models.ForeignKey(ContentType,  on_delete=models.CASCADE )
    object_id = models.PositiveIntegerField()
    associated_object = GenericForeignKey('content_type', 'object_id')

class PositionData(HistoricalData):
    quantity = models.FloatField()
    average_cost = models.FloatField()

class AssetData(PositionData):
    close = models.FloatField()
    dividends = models.FloatField()
    stock_splits = models.FloatField()