from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from cloudinary_storage.storage import MediaCloudinaryStorage

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class StaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=500)
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True)
    skills = models.CharField(max_length=255, default="")
    
    def get_skills(self):
        """Returns a list of skills, properly formatted and stripped"""
        if not self.skills:
            return []
        return [skill.strip() for skill in self.skills.split(',') if skill.strip()]

    def get_roles(self):
        """Returns a list of roles, properly formatted and stripped"""
        if not self.role:
            return []
        return [role.strip() for role in self.role.split(',') if role.strip()]
    
    email = models.EmailField(unique=True)
    location = models.CharField(max_length=100, blank=True, null=True)
    profile_picture = models.ImageField(
        upload_to='profile_pics/',
        storage=MediaCloudinaryStorage() if not settings.DEBUG else None,
        blank=True, 
        null=True
    )
    status = models.CharField(
        max_length=20,
        choices=[('available', 'Available'), ('unavailable', 'Unavailable')],
        default='available'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    about_me = models.TextField(blank=True)

    phone = models.CharField(max_length=20, blank=True)
    custom_status = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True, null=True)
    monday_hours = models.CharField(max_length=50, blank=True, null=True)
    tuesday_hours = models.CharField(max_length=50, blank=True, null=True)
    wednesday_hours = models.CharField(max_length=50, blank=True, null=True)
    thursday_hours = models.CharField(max_length=50, blank=True, null=True)
    friday_hours = models.CharField(max_length=50, blank=True, null=True)
    bookmarked_by = models.ManyToManyField(User, related_name='bookmarked_staff', blank=True)

    @property
    def get_display_status(self):
        if self.custom_status:  # Check custom status first
            return self.custom_status
        elif self.status == 'unavailable':
            return 'Unavailable'
        return 'Available'

    @property
    def bookmark_count(self):
        return self.bookmarked_by.count()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class ProfileView(models.Model):

    staff_profile = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='views')
    visitor = models.ForeignKey(User, on_delete=models.CASCADE)
    viewed_at = models.DateField(auto_now_add=True)  # Only store date, not time

    class Meta:
        # makin sure one view per visitor per staff profile per day to stop ppl abusin feature. repeated views after 24hrs similar to yt
        unique_together = ('staff_profile', 'visitor', 'viewed_at')
