from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views
from .views import CustomLoginView

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    path('duty-list/', views.duty_list, name='duty_list'),
    path('export-schedule/', views.export_schedule, name='export_schedule'),
    path('', views.duty_calendar, name='duty_calendar'),
    path('calendar/', views.duty_calendar, name='duty_calendar'),
    path('manage-duty-order/', views.manage_duty_order, name='manage_duty_order'),
    path('toggle-holiday/', views.toggle_holiday, name='toggle_holiday'),
    path('generate-monthly-schedule/', views.generate_monthly_schedule, name='regenerate_schedule'),
    path('get-available-swaps/', views.get_available_swaps, name='get_available_swaps'),
    path('request-swap/', views.request_swap, name='request_swap'),
    path('handle-swap-request/<int:request_id>/', views.handle_swap_request, name='handle_swap_request'),
]