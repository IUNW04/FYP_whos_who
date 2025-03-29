from django.urls import path
from . import views
from django.conf import settings
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/add-staff/', views.staff_add, name='staff_add'),
    path('admin-dashboard/edit-staff/<int:pk>/', views.staff_edit, name='staff_edit'),
    path('admin-dashboard/delete-staff/<int:pk>/', views.staff_delete, name='staff_delete'),
    path('staff/<int:pk>/', views.staff_profile, name='staff_profile'),
    path('department/<int:pk>/edit/', views.edit_department, name='edit_department'),
    path('department/<int:pk>/delete/', views.delete_department, name='delete_department'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('password-reset/', views.password_reset_view, name='password_reset'),
    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(template_name='WhosWhoApp/password_reset_done.html'),
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(template_name='WhosWhoApp/password_reset_confirm.html'),
         name='password_reset_confirm'),
    path('password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(template_name='WhosWhoApp/password_reset_complete.html'),
         name='password_reset_complete'),
    path('users/', views.user_list, name='user_list'),
    path('user/add/', views.add_user, name='add_user'),
    path('user/<int:pk>/edit/', views.edit_user, name='edit_user'),
    path('user/<int:pk>/delete/', views.delete_user, name='delete_user'),
    path('staff-dashboard/', views.staff_dashboard, name='staff_dashboard'),
    path('department/add/', views.add_department, name='add_department'),

    path('api/chat/', views.chat_with_ai, name='chat_with_ai'),
    path('chat-with-ai/', views.chat_with_ai, name='chat_with_ai'),
    path('chat-interface/', views.chat_interface, name='chat_interface'),
    path('bookmarks/', views.bookmarks, name='bookmarks'),
    path('chat-history/', views.chat_history, name='chat_history'),
    path('bookmark-staff/<int:staff_id>/', views.bookmark_staff, name='bookmark_staff'),
    path('toggle_bookmark/<int:staff_id>/', views.toggle_bookmark, name='toggle_bookmark'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('staff/bulk-import/', views.bulk_staff_import, name='bulk_staff_import'),
    path('staff/download-template/', views.download_template, name='download_template'),
]