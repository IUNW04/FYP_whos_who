from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve

class AdminAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if the current URL is an admin route
        if request.path.startswith('/admin-dashboard'):
            # If user is logged in but their not a superuser, redirect them
            if request.user.is_authenticated and not request.user.is_superuser:
                messages.error(request, 'You do not have permission to access the admin dashboard.')
                if hasattr(request.user, 'staffprofile'):
                    return redirect('staff_dashboard')
                return redirect('home')
                
        response = self.get_response(request)
        return response
