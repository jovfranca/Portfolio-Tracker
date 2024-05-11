from django.db import models

class User(models.Model):
    name = models.CharField(max_length=100)
    registration_number = models.PositiveIntegerField()
    email = models.EmailField(unique=True)
    pass_hash = models.CharField(max_length=128)

    def new_portfolio(self):
        pass

    def __str__(self):
        return self.name
