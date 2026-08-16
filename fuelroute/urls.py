from django.urls import path

from fuelroute import views

urlpatterns = [
    path('healthz/', views.healthz, name='healthz'),
    path('api/v1/route/', views.RouteView.as_view(), name='route'),
    path('map/', views.map_view, name='map'),
]
