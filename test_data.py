from WhosWhoApp.models import StaffProfile, Department
from django.contrib.auth.models import User

# Creates a test department if it doesn't exist
dept, _ = Department.objects.get_or_create(name="Engineering")

# Creating a test user with skills
staff = StaffProfile.objects.create(
    name="Test Engineer",
    role="Software Engineer",
    department=dept,
    email="test@example.com",
    skills="Python, Django, JavaScript, AWS",
    status="available"
)