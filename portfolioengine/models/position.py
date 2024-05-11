from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from .historical_data import PositionData

class Position(models.Model):
    asset= models.ForeignKey("Asset", on_delete=models.CASCADE, related_name= "positions")
    broker = models.ForeignKey("Broker", on_delete=models.CASCADE,  related_name= "positions")
    allocation_class = models.ForeignKey( "AllocationClass", on_delete=models.CASCADE,  related_name= "positions")
    portfolio = models.ForeignKey("Portfolio", on_delete=models.CASCADE,  related_name="positions")
    historical_data = GenericRelation(PositionData)