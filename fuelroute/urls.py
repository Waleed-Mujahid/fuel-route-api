from django.urls import path

from fuelroute import views

urlpatterns = [
    path('healthz/', views.healthz, name='healthz'),
]
