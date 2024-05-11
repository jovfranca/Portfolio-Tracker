from django.db import models

class Transaction(models.Model):
    date_time = models.DateTimeField()
    type = models.CharField(max_length=10)
    position = models.ForeignKey("Position", on_delete=models.CASCADE,  related_name="transactions")
    quantity = models.FloatField()
    price = models.FloatField()
    brokerage_fee = models.FloatField()
    other_fees = models.FloatField()
    notes = models.CharField(max_length=200)
