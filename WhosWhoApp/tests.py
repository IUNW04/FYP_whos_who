from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from .models import StaffProfile, Department

class StaffDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='teststaff',
            password='testpass123'
        )
        
        self.department = Department.objects.create(name='Test Department')
        
        self.staff_profile = StaffProfile.objects.create(
            user=self.user,
            name='Test Staff',
            role='Tester',
            department=self.department,
            email='test@test.com'
        )
        
        self.client = Client()

    def test_dashboard_access(self):
        response = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 302)
        
        self.client.login(username='teststaff', password='testpass123')
        response = self.client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 200)
        
    def test_status_update(self):
        self.client.login(username='teststaff', password='testpass123')
        
        response = self.client.post(reverse('staff_dashboard'), {'toggle_status': 'true'})
        self.staff_profile.refresh_from_db()
        self.assertEqual(self.staff_profile.status, 'unavailable')

