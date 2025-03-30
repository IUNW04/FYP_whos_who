from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpResponse
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.db import IntegrityError
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from django.contrib import messages
from .models import StaffProfile, Department, ProfileView  # Add ProfileView to imports
from .forms import AdminStaffProfileForm, StaffProfileForm
from django.db.models import Q, Count
from django.utils import timezone
from datetime import datetime, timedelta
import json
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.db import transaction
from django.http import JsonResponse
from .services.ai_assistant import AIAssistant
import json
import logging
import re
from django.middleware.csrf import get_token  # Add this import
from django.views.decorators.http import require_http_methods

try:
    ai_assistant = AIAssistant()
except Exception as e:
    logging.error(f"Failed to initialize AI assistant: {str(e)}")
    ai_assistant = None

@login_required
def home(request):
    staff_profiles = StaffProfile.objects.all().select_related('department')
    all_departments = Department.objects.all()
    # Get all unique roles from staff profiles
    all_roles = set()
    for staff in StaffProfile.objects.exclude(role=''):
        all_roles.update(staff.get_roles())
    all_roles = sorted(list(all_roles))
    
    all_status = ['available', 'unavailable']

    # Initialize all_skills as an empty set
    all_skills = set()

    search_query = request.GET.get('search', '')
    selected_departments = request.GET.getlist('department[]')
    selected_roles = request.GET.getlist('role[]')
    selected_status = request.GET.getlist('status[]')
    current_letter = request.GET.get('letter', '')

    # Apply filters
    if search_query:
        staff_profiles = staff_profiles.filter(
            Q(name__icontains=search_query) |
            Q(role__icontains=search_query) |
            Q(department__name__icontains=search_query) |
            Q(custom_status__icontains=search_query)
        )

    if selected_departments:
        staff_profiles = staff_profiles.filter(department__id__in=selected_departments)

    # Modify the role filter to handle individual roles
    if selected_roles:
        staff_profiles = [staff for staff in staff_profiles if 
                         any(selected in staff.get_roles() 
                             for selected in selected_roles)]

    if selected_status:
        staff_profiles = staff_profiles.filter(status__in=selected_status)

    if current_letter:
        staff_profiles = staff_profiles.filter(name__istartswith=current_letter)

    # Get all unique skills from staff profiles
    for staff in StaffProfile.objects.exclude(skills=''):
        all_skills.update(staff.get_skills())
    all_skills = sorted(list(all_skills))

    # Get selected skills from request
    selected_skills = request.GET.getlist('skills[]')

    # Filter by skills if any are selected
    if selected_skills:
        staff_profiles = [staff for staff in staff_profiles if 
                         any(selected in staff.get_skills() 
                             for selected in selected_skills)]

    # Add status display logic for each staff profile
    for staff in staff_profiles:
        if staff.status == 'unavailable':
            staff.display_status = 'Unavailable'
        elif staff.custom_status:
            staff.display_status = staff.custom_status
        else:
            staff.display_status = 'Available'

    # Add bookmark status for authenticated users
    if request.user.is_authenticated:
        bookmarked_staff = request.user.bookmarked_staff.values_list('id', flat=True)
    else:
        bookmarked_staff = []

    # Add these statistics calculations
    total_staff = StaffProfile.objects.count()
    available_staff = StaffProfile.objects.filter(status='available').count()
    departments_count = Department.objects.count()

    return render(request, 'WhosWhoApp/home.html', {
        'staff_profiles': staff_profiles,
        'departments': all_departments,  # Changed from departments to all_departments
        'roles': all_roles,
        'status_choices': all_status,
        'all_skills': all_skills,
        'selected_departments': selected_departments,
        'selected_roles': selected_roles,
        'selected_status': selected_status,
        'selected_skills': selected_skills,
        'search_query': search_query,
        'current_letter': current_letter,
        'bookmarked_staff': bookmarked_staff,
        # Add these new context variables
        'total_staff': total_staff,
        'available_staff': available_staff,
        'departments_count': departments_count,
        'csrf_token': get_token(request),  # Add this line
    })

@login_required
def admin_dashboard(request):
    # Get active tab from query params or default to staff
    active_tab = request.GET.get('active_tab', 'staff')
    
    # Get department message if it exists
    dept_message = None
    if 'dept_message' in request.session:
        dept_message = request.session['dept_message']
        del request.session['dept_message']
    
    # Base querysets
    staff_profiles = StaffProfile.objects.all()
    departments = Department.objects.all()
    users = User.objects.all()


    # Get search parameters for each section
    staff_search = request.GET.get('staff_search', '')
    dept_search = request.GET.get('dept_search', '')
    user_search = request.GET.get('user_search', '')
    role_filter = request.GET.get('role_filter', '')
    status_filter = request.GET.get('status', '')

    # Apply filters...
    if staff_search:
        staff_profiles = staff_profiles.filter(
            Q(name__icontains=staff_search) |
            Q(role__icontains=staff_search) |
            Q(department__name__icontains=staff_search) |
            Q(email__icontains=staff_search)
        ).distinct()
    
    if status_filter:
        staff_profiles = staff_profiles.filter(status=status_filter)

    if dept_search:
        departments = departments.filter(Q(name__icontains=dept_search)).distinct()
    
    if user_search:
        users = users.filter(
            Q(username__icontains=user_search) |
            Q(email__icontains=user_search)
        ).distinct()
    
    if role_filter:
        if role_filter == 'admin':
            users = users.filter(is_superuser=True)
        elif role_filter == 'user':
            users = users.filter(is_superuser=False)

    # Department-specific data
    department_data = {}
    for dept in departments:
        dept_staff = StaffProfile.objects.filter(department=dept)
        department_data[dept.id] = {
            'status_distribution': [
                dept_staff.filter(status='available').count(),
                dept_staff.filter(status='unavailable').count()
            ],
            'growth_data': [
                dept_staff.filter(created_at__lte=timezone.now() - timedelta(days=i*30)).count()
                for i in range(5, -1, -1)
            ]
        }

    # Analytics Data
    department_data = {}
    departments_list = []
    for dept in departments:
        dept_staff = StaffProfile.objects.filter(department=dept)
        department_data[dept.id] = {
            'id': dept.id,
            'name': dept.name,
            'status_distribution': [
                dept_staff.filter(status='available').count(),
                dept_staff.filter(status='unavailable').count()
            ],
            'growth_data': [
                dept_staff.filter(created_at__lte=timezone.now() - timedelta(days=i*30)).count()
                for i in range(5, -1, -1)
            ]
        }
        departments_list.append({'id': dept.id, 'name': dept.name})

    staff_counts = [StaffProfile.objects.filter(department=dept).count() for dept in departments]

    # Most viewed staff with IDs
    most_viewed_staff = StaffProfile.objects.annotate(
        unique_views=Count('views', distinct=True)
    ).order_by('-unique_views')[:10]
    
    # Most bookmarked staff
    most_bookmarked_staff = StaffProfile.objects.annotate(
        bookmark_total=Count('bookmarked_by')
    ).order_by('-bookmark_total')[:10]
    
    staff_data = [{'id': staff.id, 'name': staff.name, 'views': staff.unique_views} 
                  for staff in most_viewed_staff]
                  
    bookmark_data = [{'id': staff.id, 'name': staff.name, 'bookmarks': staff.bookmark_total} 
                  for staff in most_bookmarked_staff]

    # Overall status distribution
    status_distribution = [
        staff_profiles.filter(status='available').count(),
        staff_profiles.filter(status='unavailable').count()
    ]

    # Growth trend (last 6 months)
    months = []
    growth_data = []
    for i in range(5, -1, -1):
        date = timezone.now() - timedelta(days=i*30)
        months.append(date.strftime('%B'))
        growth_data.append(staff_profiles.filter(created_at__lte=date).count())

    context = {
        'staff_profiles': staff_profiles.order_by('name'),
        'departments': departments.order_by('name'),
        'users': users.order_by('username'),
        'staff_search': staff_search,
        'dept_search': dept_search,
        'user_search': user_search,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'active_tab': active_tab,
        'dept_message': dept_message,  # Add department message to context

        # Analytics data
        'department_names': json.dumps([d['name'] for d in departments_list]),
        'staff_counts': json.dumps(staff_counts),
        'staff_names': json.dumps([s['name'] for s in staff_data]),
        'profile_views': json.dumps([s['views'] for s in staff_data]),
        'bookmark_staff_names': json.dumps([s['name'] for s in bookmark_data]),
        'bookmark_counts': json.dumps([s['bookmarks'] for s in bookmark_data]),
        'status_distribution': json.dumps(status_distribution),
        'months': json.dumps(months),
        'growth_data': json.dumps(growth_data),
        'departments_json': json.dumps(departments_list),
        'staff_json': json.dumps(staff_data),
        'bookmark_json': json.dumps(bookmark_data),
        'department_data': json.dumps(department_data)
    }
    
    return render(request, 'WhosWhoApp/admin_dashboard.html', context)

@login_required
def staff_add(request):
    if not request.user.is_superuser:
        return redirect('home')

    if request.method == 'POST':
        form = StaffProfileForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create User account with staff access
                    user = User.objects.create_user(
                        username=form.cleaned_data['username'],
                        email=form.cleaned_data['email'],
                        password=form.cleaned_data['password']
                    )
                    # Set staff status
                    user.is_staff = form.cleaned_data.get('is_staff', True)
                    user.save()
                    
                    # Create StaffProfile
                    staff_profile = form.save(commit=False)
                    staff_profile.user = user
                    staff_profile.save()
                    
                    messages.success(request, '[staff] Staff member and account created successfully.')
                    return redirect(f"{reverse('admin_dashboard')}?active_tab=staff")
            except Exception as e:
                messages.error(request, f'Error creating staff member: {str(e)}')
    else:
        form = StaffProfileForm()
    
    return render(request, 'WhosWhoApp/staff_form.html', {
        'form': form,
        'title': 'Add Staff'
    })

def staff_edit(request, pk):
    staff = get_object_or_404(StaffProfile, pk=pk)
    if request.method == 'POST':
        form = AdminStaffProfileForm(request.POST, request.FILES, instance=staff)
        if form.is_valid():
            # Save all fields including office hours
            updated_staff = form.save(commit=True)
            messages.success(request, '[staff] Staff member updated successfully.')
            return redirect(f"{reverse('admin_dashboard')}?active_tab=staff")
    else:
        form = AdminStaffProfileForm(instance=staff)
    return render(request, 'WhosWhoApp/staff_form.html', {'form': form, 'title': 'Edit Staff'})

def staff_delete(request, pk):
    staff = get_object_or_404(StaffProfile, pk=pk)
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get the associated user first
                user = staff.user
                # Delete the staff profile
                staff.delete()
                # Delete the user if they exist
                if user and not user.is_superuser:  # Don't delete superusers
                    user.delete()
                messages.success(request, '[staff] Staff member deleted successfully.')
            return redirect(f"{reverse('admin_dashboard')}?active_tab=staff")
        except Exception as e:
            messages.error(request, f'Error deleting staff member: {str(e)}')
            return redirect(f"{reverse('admin_dashboard')}?active_tab=staff")
    return render(request, 'WhosWhoApp/staff_confirm_delete.html', {'staff': staff})

@login_required
def staff_profile(request, pk):
    staff = get_object_or_404(StaffProfile, pk=pk)
    
    # Record unique view
    if request.user != staff.user:  # Don't count self-views
        ProfileView.objects.get_or_create(
            staff_profile=staff,
            visitor=request.user,
            viewed_at=timezone.now().date()
        )
    
    office_hours = {
        'Monday': staff.monday_hours or '',
        'Tuesday': staff.tuesday_hours or '',
        'Wednesday': staff.wednesday_hours or '',
        'Thursday': staff.thursday_hours or '',
        'Friday': staff.friday_hours or ''
    }
    
    if staff.status == 'unavailable':
        staff.display_status = 'Unavailable'
    elif staff.custom_status:
        staff.display_status = staff.custom_status
    else:
        staff.display_status = 'Available'
    
    return render(request, 'WhosWhoApp/staff_profile.html', {
        'staff': staff,
        'office_hours': office_hours
    })

from django.contrib.messages import get_messages

@login_required
def add_department(request):
    if not request.user.is_superuser:
        return redirect('home')

    # Get message from session
    dept_message = request.session.get('dept_message')
    
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            try:
                Department.objects.create(name=name)
                request.session['dept_message'] = {'type': 'success', 'text': 'Department created successfully.'}
                return redirect(f"{reverse('admin_dashboard')}?active_tab=departments")
            except IntegrityError:
                request.session['dept_message'] = {'type': 'error', 'text': 'A department with this name already exists.'}
                return render(request, 'WhosWhoApp/add_department.html')
    
    # Clear the message after rendering
    if 'dept_message' in request.session:
        del request.session['dept_message']
            
    return render(request, 'WhosWhoApp/add_department.html', {'dept_message': dept_message})

@login_required
def edit_department(request, pk):
    if not request.user.is_superuser:
        return redirect('home')
        
    department = get_object_or_404(Department, pk=pk)
    
    # Get message from session
    dept_message = request.session.get('dept_message')
    
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            try:
                department.name = name
                department.save()
                request.session['dept_message'] = {'type': 'success', 'text': 'Department updated successfully.'}
                return redirect(f"{reverse('admin_dashboard')}?active_tab=departments")
            except IntegrityError:
                dept_message = {'type': 'error', 'text': 'A department with this name already exists.'}
    
    # Clear the message after rendering
    if 'dept_message' in request.session:
        del request.session['dept_message']
            
    return render(request, 'WhosWhoApp/edit_department.html', {
        'department': department,
        'dept_message': dept_message
    })




def delete_department(request, pk):
    if request.method == 'POST':
        dept = get_object_or_404(Department, pk=pk)
        dept.delete()
        request.session['dept_message'] = {'type': 'success', 'text': 'Department deleted successfully.'}
    return redirect(f"{reverse('admin_dashboard')}?active_tab=departments")

@ensure_csrf_cookie
@csrf_protect
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            #check if user is staff member
            if hasattr(user, 'staffprofile'):
                return redirect('staff_dashboard')
            #check if superuser
            elif user.is_superuser:
                return redirect(f"{reverse('admin_dashboard')}?active_tab=staff")
            # Regular users go to home cos they dont have specific dashboard or deifferent privlags
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password')
    return render(request, 'WhosWhoApp/login.html')

@ensure_csrf_cookie
@csrf_protect
def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 != password2:
            messages.error(request, 'Passwords do not match')
            return render(request, 'WhosWhoApp/login.html')

        try:
            user = User.objects.create_user(username=username, email=email, password=password1)
            login(request, user)
            return redirect('home')
        except:
            messages.error(request, 'Error creating account')
    return render(request, 'WhosWhoApp/login.html')

def password_reset_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        new_password = request.POST.get('new_password')
        
        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            messages.success(request, 'Password successfully reset')
            return redirect('login')
        except User.DoesNotExist:
            messages.error(request, 'Email not found in our records')
            return render(request, 'WhosWhoApp/password_reset.html')
    
    return render(request, 'WhosWhoApp/password_reset.html')

def add_user(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        is_superuser = request.POST.get('is_superuser') == 'on'
        
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_superuser=is_superuser
            )
            messages.success(request, '[user] User created successfully')
            return redirect(f"{reverse('admin_dashboard')}?active_tab=users")
        except:
            messages.error(request, 'Error creating user')
    return render(request, 'WhosWhoApp/add_user.html')

@login_required
def user_list(request):
    users = User.objects.all()
    
    # Search 
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    context = {
        'users': users,
        'search_query': search_query
    }
    return render(request, 'WhosWhoApp/user_list.html', context)

@login_required
def edit_user(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        is_superuser = request.POST.get('is_superuser') == 'on'
        
        try:
            user.username = username
            user.email = email
            if password:
                user.set_password(password)
            user.is_superuser = is_superuser
            user.save()
            messages.success(request, '[user] User updated successfully')
            return redirect(f"{reverse('admin_dashboard')}?active_tab=users")
        except:
            messages.error(request, 'Error updating user')
    
    return render(request, 'WhosWhoApp/edit_user.html', {'edit_user': user})

@login_required
def delete_user(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    # Prevent self-deletion
    if user == request.user:
        messages.error(request, '[user] You cannot delete your own account')
        return redirect(f"{reverse('admin_dashboard')}?active_tab=users")
    
    try:
        user.delete()
        messages.success(request, '[user] User deleted successfully')
    except:
        messages.error(request, 'Error deleting user')
    
    return redirect('admin_dashboard')

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .forms import StaffProfileForm

@login_required
def staff_dashboard(request):
    # Use select_related for user and department, prefetch_related for views and bookmarks
    staff_profile = get_object_or_404(
        StaffProfile.objects.select_related('user', 'department')
        .prefetch_related('views', 'bookmarked_by'),
        user=request.user
    )
    
    if request.method == 'POST':
        try:
            # Get form data
            bio = request.POST.get('bio')
            about_me = request.POST.get('about_me')
            custom_status = request.POST.get('custom_status')
            status = request.POST.get('current_status')
            skills = request.POST.get('skills')

            # Handle profile pics
            if request.FILES.get('profile_picture'):
                staff_profile.profile_picture = request.FILES['profile_picture']
            
            # Update all fields
            staff_profile.bio = bio if bio is not None else staff_profile.bio
            staff_profile.about_me = about_me if about_me is not None else staff_profile.about_me
            staff_profile.custom_status = custom_status if custom_status is not None else staff_profile.custom_status
            staff_profile.status = status if status is not None else staff_profile.status
            staff_profile.skills = skills if skills is not None else staff_profile.skills
            
            # Save changes
            staff_profile.save()
            
            messages.success(request, 'Changes saved successfully!')
            return redirect('staff_dashboard')
            
        except Exception as e:
            messages.error(request, f'Error saving changes: {str(e)}')
    
    return render(request, 'WhosWhoApp/staff_dashboard.html', {
        'staff_profile': staff_profile
    })

@require_http_methods(["POST"])
def chat_with_ai(request):
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '')
        
        # Get raw response first
        raw_response = ai_assistant.get_raw_response(user_message)
        
        # Extract staff names from response
        staff_names = re.findall(r'\b([A-Z][a-z]+ [A-Z][a-z]+)\b', raw_response)
        
        # Get staff info separately
        staff_info_list = []
        for name in staff_names:
            try:
                staff = StaffProfile.objects.get(name=name)
                staff_info = {
                    'id': staff.id,
                    'name': staff.name,
                    'role': staff.role,
                    'department': staff.department.name if staff.department else 'Not specified'
                }
                staff_info_list.append(staff_info)
            except StaffProfile.DoesNotExist:
                continue
        
        # Add links to response after getting staff info
        response = raw_response
        for staff in staff_info_list:
            response = response.replace(
                staff['name'],
                f'<a href="/staff/{staff["id"]}" class="staff-link">{staff["name"]}</a>'
            )
        
        return JsonResponse({
            'response': response,
            'staff_info_list': staff_info_list
        })
        
    except Exception as e:
        logging.error(f"Error in chat_with_ai: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def bookmark_staff(request, staff_id):
    staff = get_object_or_404(StaffProfile, id=staff_id)
    is_bookmarked = request.user in staff.bookmarked_by.all()
    
    if is_bookmarked:
        staff.bookmarked_by.remove(request.user)
        return JsonResponse({'status': 'removed'})
    else:
        staff.bookmarked_by.add(request.user)
        return JsonResponse({'status': 'added'})

@login_required
def bookmarks(request):
    # Get only the staff profiles that are bookmarked by the current user
    bookmarked_staff = StaffProfile.objects.filter(bookmarked_by=request.user)
    return render(request, 'WhosWhoApp/bookmarks.html', {'bookmarks': bookmarked_staff})

@login_required
def chat_history(request):
    return render(request, 'WhosWhoApp/chat_history.html')


def chat_interface(request):
    """View for the dedicated chat interface page"""
    return render(request, 'WhosWhoApp/chat_interface.html')

@login_required
def toggle_bookmark(request, staff_id):
    try:
        staff = get_object_or_404(StaffProfile, id=staff_id)
        
        if staff.bookmarked_by.filter(id=request.user.id).exists():
            staff.bookmarked_by.remove(request.user)
            bookmarked = False
        else:
            staff.bookmarked_by.add(request.user)
            bookmarked = True
        
        return JsonResponse({
            'status': 'success',
            'bookmarked': bookmarked,
            'bookmark_count': staff.bookmark_count  # Add to the current count
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

import xlsxwriter
from io import BytesIO
from django.http import HttpResponse
from .utils.excel_import import process_staff_excel

@login_required
def bulk_staff_import(request):
    if not request.user.is_superuser:
        return redirect('home')

    context = {}
    if request.method == 'POST' and request.FILES.get('excel_file'):
        success, message, error_records = process_staff_excel(request.FILES['excel_file'])
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)
        context['error_records'] = error_records

    return render(request, 'WhosWhoApp/bulk_staff_import.html', context)

@login_required
def download_template(request):
    if not request.user.is_superuser:
        return redirect('home')

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()

    headers = [
        'name', 'email', 'username', 'password', 'department', 'role',
        'location', 'monday_hours', 'tuesday_hours', 'wednesday_hours',
        'thursday_hours', 'friday_hours'
    ]
    
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#4F46E5',
        'font_color': 'white',
        'border': 1
    })

    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
        worksheet.set_column(col, col, 15)

    example_data = [
        'John Doe',
        'john@example.com',
        'johndoe',
        'password123',
        'IT Department',
        'Software Engineer',
        'Room 101',
        '9:00 AM - 5:00 PM',
        '9:00 AM - 5:00 PM',
        '9:00 AM - 5:00 PM',
        '9:00 AM - 5:00 PM',
        '9:00 AM - 5:00 PM'
    ]
    
    for col, value in enumerate(example_data):
        worksheet.write(1, col, value)

    workbook.close()
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=staff_import_template.xlsx'
    
    return response
