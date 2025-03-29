import pandas as pd
from django.contrib.auth.models import User
from ..models import StaffProfile, Department
from django.db import transaction
from django.db.models import Q

def validate_staff_data(df):
    required_columns = ['name', 'email', 'username', 'password', 'department', 'role']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        return False, f"Missing required columns: {', '.join(missing_columns)}"
    return True, None

def process_staff_excel(file):
    try:
        df = pd.read_excel(file)
        is_valid, error_message = validate_staff_data(df)
        if not is_valid:
            return False, error_message, []

        success_count = 0
        error_records = []

        with transaction.atomic():
            for index, row in df.iterrows():
                try:
                    username = row['username'].strip()
                    email = row['email'].strip()
                    
                    # Check if user already exists
                    existing_user = User.objects.filter(Q(username=username) | Q(email=email)).first()
                    if existing_user:
                        # Delete existing user and associated staff profile if they exist
                        StaffProfile.objects.filter(user=existing_user).delete()
                        existing_user.delete()
                    
                    # Get or create department
                    department, _ = Department.objects.get_or_create(name=row['department'])
                    
                    # Create new user
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=row['password'].strip()
                    )
                    user.is_staff = True
                    user.save()

                    # Create staff profile
                    staff_profile = StaffProfile.objects.create(
                        user=user,
                        name=row['name'].strip(),
                        department=department,
                        role=row['role'].strip(),
                        email=email,
                        status='available',
                        location=row.get('location', '').strip(),
                        monday_hours=row.get('monday_hours', '').strip(),
                        tuesday_hours=row.get('tuesday_hours', '').strip(),
                        wednesday_hours=row.get('wednesday_hours', '').strip(),
                        thursday_hours=row.get('thursday_hours', '').strip(),
                        friday_hours=row.get('friday_hours', '').strip()
                    )
                    success_count += 1

                except Exception as e:
                    error_records.append({
                        'row': index + 2,
                        'name': row['name'],
                        'error': str(e)
                    })
                    raise

        return True, f"Successfully imported {success_count} staff members.", error_records

    except Exception as e:
        return False, f"Error processing file: {str(e)}", []
