from django.contrib import admin
from .models import AllocationClass
from .models import Asset
from .models import Broker
from .models import Country
from .models import HistoricalData
from .models import PositionData
from .models import AssetData
from .models import Portfolio
from .models import Position
from .models import Transaction
from .models import User

# Register your models here.
admin.site.register(AllocationClass)
admin.site.register(Asset)
admin.site.register(Broker)
admin.site.register(Country)
admin.site.register(HistoricalData)
admin.site.register(PositionData)
admin.site.register(AssetData)
admin.site.register(Portfolio)
admin.site.register(Position)
admin.site.register(Transaction)
admin.site.register(User)