from django.db import models

class Broker(models.Model):
    name = models.CharField(max_length=30)
    registration_number = models.IntegerField()