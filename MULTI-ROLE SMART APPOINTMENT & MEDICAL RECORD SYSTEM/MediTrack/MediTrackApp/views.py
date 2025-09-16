import os
import io
import csv
import json
import logging
import psutil
import time
from django.db.models import Sum
from datetime import datetime, timedelta
from django.core.cache import cache
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.db import transaction, connection
from django.core.management import call_command
from .decorators import role_required
from .models import *
from .forms import *
from .reports import *

# Initialize logger
logger = logging.getLogger(__name__)

# *************************************************************************
#                         CORE VIEWS
# *************************************************************************


def home_redirect(request):
    """
    Redirect authenticated users to their role-specific dashboard.
    Unauthenticated users are redirected to the home page.
    """
    if not request.user.is_authenticated:
        return redirect('home')

    role_dashboard_map = {
        'admin': 'admin_dashboard',
        'doctor': 'doctor_dashboard',
        'patient': 'patient_dashboard'
    }

    return redirect(role_dashboard_map.get(request.user.role, 'home'))


def home(request):
    """Home page view for unauthenticated users."""
    return render(request, "index.html")


# *************************************************************************
#                         AUTHENTICATION VIEWS
# *************************************************************************

def register_view(request):
    """Handle user registration with role-based profile creation."""
    if request.method == "POST":
        form = UserRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.set_password(form.cleaned_data["password1"])
                    user.role = form.cleaned_data.get("role")
                    user.is_active = False  # Requires admin approval
                    user.save()

                    # Create role-specific profile
                    if user.role == "doctor":
                        DoctorProfile.objects.get_or_create(user=user)
                    elif user.role == "patient":
                        PatientProfile.objects.get_or_create(user=user)

                    messages.success(
                        request,
                        "Registration successful! Your account is pending approval."
                    )
                    return redirect("login")
            except Exception as e:
                logger.error(f"Registration error: {str(e)}")
                messages.error(
                    request, "Registration failed. Please try again.")
    else:
        form = UserRegistrationForm()

    return render(request, "registration/register.html", {"form": form})


def login_view(request):
    """Handle user authentication and role-based redirection."""
    if request.method == "POST":
        form = UserLoginForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()

            # Check if non-admin user is approved
            if user.role != 'admin' and not user.is_active:
                messages.error(
                    request,
                    "Your account is pending approval. Please wait for admin activation."
                )
                return redirect('login')

            login(request, user)

            # Check profile completion based on role
            profile_complete = True
            if user.role == 'doctor':
                profile = user.doctor_profile
                required_fields = ['specialization', 'city', 'license_number']
                profile_complete = all(getattr(profile, field)
                                       for field in required_fields)
            elif user.role == 'patient':
                profile = user.patient_profile
                required_fields = ['blood_group', 'emergency_contact']
                profile_complete = all(getattr(profile, field)
                                       for field in required_fields)

            if not profile_complete:
                messages.info(
                    request, "Please complete your profile before continuing")
                return redirect('edit_profile')

            # Redirect to appropriate dashboard
            dashboard_redirects = {
                'admin': 'admin_dashboard',
                'doctor': 'doctor_dashboard',
                'patient': 'patient_dashboard'
            }

            return redirect(dashboard_redirects.get(user.role, 'home'))
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = UserLoginForm()

    return render(request, "registration/login.html", {'form': form})


def password_reset(request):
    redirect("password_reset")
# def guest_booking(request):
#     redirect("guest_booking")


@login_required
def logout_view(request):
    """Handle user logout."""
    logout(request)
    return redirect("login")


@login_required
def edit_profile(request):
    """Handle profile editing with role-specific forms."""
    role_form_map = {
        'doctor': (DoctorProfileForm, 'doctor_profile'),
        'patient': (PatientProfileForm, 'patient_profile'),
        'admin': (AdminUserForm, 'admin_profile')
    }

    form_class, profile_attr = role_form_map.get(
        request.user.role, (None, None))

    if not form_class:
        messages.error(request, "Profile editing not available for this role")
        return redirect('home_redirect')

    profile = getattr(request.user, profile_attr)

    if request.method == 'POST':
        form = form_class(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully")
            return redirect('edit_profile')
    else:
        form = form_class(instance=profile)

    return render(request, "profiles/edit_profile.html", {'form': form})


# *************************************************************************
#                         DASHBOARD VIEWS
# *************************************************************************

@login_required
@role_required(["admin"])
def admin_dashboard(request):
    """Admin dashboard with system statistics and recent activity."""
    user_stats = {
        'total': User.objects.count(),
        'doctors': User.objects.filter(role='doctor').count(),
        'patients': User.objects.filter(role='patient').count(),
        'active': User.objects.filter(is_active=True).count(),
        'blocked': User.objects.filter(is_active=False).count(),
    }

    appointment_stats = {
        'total': Appointment.objects.count(),
        'today': Appointment.objects.filter(date=timezone.now().date()).count(),
        'pending': Appointment.objects.filter(status='pending').count(),
        'completed': Appointment.objects.filter(status='completed').count(),
    }

    recent_activity = ActivityLog.objects.order_by('-created_at')[:10]
    announcements = Announcement.objects.filter(
        is_active=True).order_by('-created_at')[:5]

    context = {
        'user_stats': user_stats,
        'appointment_stats': appointment_stats,
        'recent_activity': recent_activity,
        'announcements': announcements,
    }
    return render(request, "dashboards/admin_dashboard.html", context)


@login_required
@role_required(["doctor"])
def doctor_dashboard(request):
    """Doctor dashboard with upcoming appointments."""
    today = timezone.now().date()
    appointments = (
        Appointment.objects.filter(
            doctor=request.user.doctor_profile,
            date__gte=today
        )
        .order_by("date", "time")
    )
    patient_count = Appointment.objects.filter(
        doctor=request.user.doctor_profile
    ).count()
    prescription_count = Prescription.objects.filter(
        appointment__doctor=request.user.doctor_profile
    ).count()
    recent_prescriptions = (
        Prescription.objects.filter(
            appointment__doctor=request.user.doctor_profile)
        .order_by("-created_at")[:5]  # last 5 prescriptions
    )

    return render(request, "dashboards/doctor_dashboard.html", {"appointments": appointments, "patient_count": patient_count, "prescription_count": prescription_count, "recent_prescriptions": recent_prescriptions})


@login_required
@role_required(["patient"])
def patient_dashboard(request):
    """Patient dashboard with appointments and prescriptions."""
    today = timezone.now().date()
    appointments = (
        Appointment.objects.filter(
            patient=request.user.patient_profile,
            date__gte=today
        )
        .order_by("date", "time")
    )
    prescriptions = Prescription.objects.filter(
        appointment__patient=request.user.patient_profile
    ).order_by("-created_at")

    return render(
        request,
        "dashboards/patient_dashboard.html",
        {"appointments": appointments, "prescriptions": prescriptions},
    )


# *************************************************************************
#                         APPOINTMENT MANAGEMENT VIEWS
# *************************************************************************

@login_required
@role_required(["doctor"])
def doctor_appointments(request):
    """Doctor appointments view with filtering and pagination."""
    # Get the doctor's profile
    doctor_profile = request.user.doctor_profile

    # Get all appointments for this doctor
    appointments = Appointment.objects.filter(
        doctor=doctor_profile).order_by('-date', '-time')

    # Apply filters
    status_filter = request.GET.get('status')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    reason_filter = request.GET.get('reason')

    if status_filter:
        appointments = appointments.filter(status=status_filter)

    if start_date:
        appointments = appointments.filter(date__gte=start_date)

    if end_date:
        appointments = appointments.filter(date__lte=end_date)

    if reason_filter:
        appointments = appointments.filter(reason=reason_filter)

    # Get statistics
    today = timezone.now().date()
    today_appointments = appointments.filter(date=today)
    pending_appointments = appointments.filter(status='pending')
    weekly_completed = appointments.filter(
        status='completed',
        date__gte=today - timedelta(days=7)
    )
    cancelled_appointments = appointments.filter(status='cancelled')

    # Pagination
    paginator = Paginator(appointments, 20)  # Show 20 appointments per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'appointments': page_obj,
        'today_appointments': today_appointments,
        'pending_appointments': pending_appointments,
        'weekly_completed': weekly_completed,
        'cancelled_appointments': cancelled_appointments,
        'doctor_profile': doctor_profile,
        'current_date': today,
        'appointment_reasons': Appointment.REASON_CHOICES,
        'stats': {
            'confirmed': appointments.filter(status='confirmed').count(),
            'completed': appointments.filter(status='completed').count(),
            'pending': appointments.filter(status='pending').count(),
            'cancelled': appointments.filter(status='cancelled').count(),
        }
    }

    # Handle CSV export
    if request.GET.get('export') == 'csv':
        return export_appointments_csv(appointments)

    return render(request, "doctor/doctor_appointments.html", context)


def export_appointments_csv(appointments):
    """Export appointments as CSV."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="appointments_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Patient Name', 'Date', 'Time', 'Status', 'Reason',
        'Symptoms', 'Created At', 'Updated At'
    ])

    for appointment in appointments:
        writer.writerow([
            appointment.patient.user.get_full_name(),
            appointment.date,
            appointment.time,
            appointment.get_status_display(),
            appointment.get_reason_display(),
            appointment.symptoms,
            appointment.created_at,
            appointment.updated_at
        ])

    return response


@login_required
@role_required(["doctor"])
def appointment_detail_ajax(request, appointment_id):
    """AJAX view for appointment details."""
    appointment = get_object_or_404(
        Appointment,
        id=appointment_id,
        doctor=request.user.doctor_profile
    )

    context = {
        'appointment': appointment
    }

    return render(request, 'doctor/appointment_detail.html', context)


@login_required
@role_required(["patient"])
def book_appointment(request):
    """Handle appointment booking by patients."""
    if request.method == "POST":
        form = AppointmentBookingForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Appointment booked successfully!")
            return redirect("patient_dashboard")
    else:
        form = AppointmentBookingForm(user=request.user)

    return render(request, "book_appointment.html", {"form": form})

# Patient Details View


@login_required
def patient_details(request, patient_id):
    # sirf doctor/admin access kar sake
    if request.user.role not in ['doctor', 'admin']:
        return redirect('dashboard')

    patient = get_object_or_404(User, id=patient_id, role='patient')
    appointments = Appointment.objects.filter(
        patient=patient).order_by('-date')

    context = {
        'patient': patient,
        'appointments': appointments
    }
    return render(request, 'patient/patient_details.html', context)


@login_required
@role_required(["doctor"])
def appointment_update_status(request, appointment_id):
    """Handle appointment status updates by doctors."""
    appointment = get_object_or_404(
        Appointment,
        id=appointment_id,
        doctor=request.user.doctor_profile
    )

    if request.method == "POST":
        form = AppointmentStatusForm(request.POST, instance=appointment)
        if form.is_valid():
            form.save()
            messages.success(request, "Appointment status updated!")
            return redirect("doctor_dashboard")
    else:
        form = AppointmentStatusForm(instance=appointment)

    return render(request, "appointment_status.html", {"form": form})


@login_required
@role_required(["admin"])
def appointment_management(request):
    """Admin view for managing appointments with filtering."""
    appointments = Appointment.objects.all().order_by('-date', '-time')
    filter_form = AppointmentFilterForm(request.GET or None)

    if filter_form.is_valid():
        date_from = filter_form.cleaned_data.get('date_from')
        date_to = filter_form.cleaned_data.get('date_to')
        status = filter_form.cleaned_data.get('status')
        doctor = filter_form.cleaned_data.get('doctor')
        patient = filter_form.cleaned_data.get('patient')

        if date_from:
            appointments = appointments.filter(date__gte=date_from)
        if date_to:
            appointments = appointments.filter(date__lte=date_to)
        if status:
            appointments = appointments.filter(status=status)
        if doctor:
            appointments = appointments.filter(doctor=doctor)
        if patient:
            appointments = appointments.filter(patient=patient)

    paginator = Paginator(appointments, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'total_appointments': appointments.count(),
    }
    return render(request, "admin/appointment_management.html", context)


@login_required
@role_required(["admin"])
def view_appointment(request, appointment_id):
    """Admin view for detailed appointment information."""
    appointment = get_object_or_404(Appointment, id=appointment_id)
    return render(request, "admin/view_appointment.html", {'appointment': appointment})


@login_required
@role_required(["admin"])
def appointment_analytics(request):
    """Display appointment statistics and analytics."""
    total_appointments = Appointment.objects.count()
    today = timezone.now().date()
    today_appointments = Appointment.objects.filter(date=today).count()
    avg_daily = round(total_appointments / 30, 1) if total_appointments else 0

    status_counts = Appointment.objects.values('status').annotate(
        count=Count('status')
    ).order_by('-count')

    for status in status_counts:
        status["percentage"] = round(
            (status["count"] / total_appointments) * 100, 1
        ) if total_appointments else 0

    start_date = today - timedelta(days=30)
    weekly_data = Appointment.objects.filter(
        date__gte=start_date
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')

    top_doctors = DoctorProfile.objects.annotate(
        appointment_count=Count('appointment')
    ).order_by('-appointment_count')[:5]

    context = {
        "total_appointments": total_appointments,
        "today_appointments": today_appointments,
        "avg_daily": avg_daily,
        "status_counts": status_counts,
        "weekly_data": weekly_data,
        "top_doctors": top_doctors,
    }
    return render(request, "admin/appointment_analytics.html", context)


# *************************************************************************
#                         PRESCRIPTION MANAGEMENT VIEWS
# *************************************************************************


@login_required
@role_required(["doctor"])
def create_prescription(request, appointment_id):
    """Handle prescription creation by doctors."""
    appointment = get_object_or_404(
        Appointment,
        id=appointment_id,
        doctor=request.user.doctor_profile
    )

    if request.method == "POST":
        form = PrescriptionForm(request.POST)
        if form.is_valid():
            prescription = form.save(commit=False)
            prescription.appointment = appointment
            prescription.save()
            messages.success(request, "Prescription created successfully!")
            return redirect("doctor_dashboard")
    else:
        form = PrescriptionForm()

    return render(request, "doctor/create_prescription.html", {"form": form, "appointment": appointment})


@login_required
@role_required(["doctor"])
def edit_prescription(request, prescription_id):
    """Handle prescription editing by doctors."""
    prescription = get_object_or_404(
        Prescription,
        id=prescription_id,
        appointment__doctor=request.user.doctor_profile,
    )

    if request.method == "POST":
        form = PrescriptionForm(request.POST, instance=prescription)
        if form.is_valid():
            form.save()
            messages.success(request, "Prescription updated successfully!")
            return redirect("prescription_list")
        else:
            # Debug: Print form errors to console
            print("Form errors:", form.errors)
            messages.error(request, "Please correct the errors below.")
    else:
        form = PrescriptionForm(instance=prescription)

    context = {
        "form": form, 
        "prescription": prescription,
        "appointment": prescription.appointment
    }
    return render(request, "edit_prescription.html", context)

@login_required
@role_required(["doctor"])
def delete_prescription(request, prescription_id):
    """Allow doctor to delete a prescription."""
    prescription = get_object_or_404(
        Prescription,
        id=prescription_id,
        appointment__doctor=request.user.doctor_profile,
    )

    if request.method == "POST":
        prescription.delete()
        messages.success(request, "Prescription deleted successfully!")
        return redirect("prescription_list")

    return render(request, "doctor/delete_prescription.html", {"prescription": prescription})



@login_required
@role_required(["patient"])
def patient_prescriptions_list(request):
    """Display patient's prescription history."""
    prescriptions = Prescription.objects.filter(
        appointment__patient=request.user.patient_profile
    )
    return render(request, "patient/patient_prescriptions_list.html", {"prescriptions": prescriptions})


@login_required
@role_required(["patient"])
def download_prescription(request, id):
    return render(request, "download_prescription.html")


@login_required
@role_required(["patient"])
def share_prescription(request, id):
    return render(request, "share_prescription.html")


@login_required
@role_required(["doctor"])
def prescription_list(request):
    """Display prescriptions created by the doctor."""
    prescriptions = Prescription.objects.filter(
        appointment__doctor=request.user.doctor_profile
    ).order_by("-created_at")   # latest first
    return render(request, "doctor/prescription_list.html", {"prescriptions": prescriptions})


# *************************************************************************
#                         MEDICAL RECORDS VIEWS
# *************************************************************************

@login_required
@role_required(["patient"])
def upload_medical_record(request):
    """Handle medical record uploads by patients."""
    if request.method == "POST":
        form = MedicalRecordForm(request.POST, request.FILES)
        if form.is_valid():
            record = form.save(commit=False)
            record.patient = request.user.patient_profile
            record.save()
            messages.success(request, "Medical record uploaded successfully!")
            return redirect("patient_dashboard")
    else:
        form = MedicalRecordForm()

    return render(request, "upload_medical_record.html", {"form": form})


@login_required
@role_required(["doctor"])
def doctor_patient_record(request, patient_id):
    """Display patient medical records for doctors."""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    records = MedicalRecord.objects.filter(
        patient=patient
    ).order_by("-uploaded_at")

    return render(request, "doctor/doctor_patient_record.html", {"patient": patient, "records": records})

@login_required
@role_required(["doctor"])
def add_medical_record(request, patient_id):
    """Add a new medical record for a patient."""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    if request.method == "POST":
        form = MedicalRecordForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                record = form.save(commit=False)
                record.patient = patient
                record.doctor = request.user.doctorprofile
                record.save()
                
                messages.success(request, "Medical record added successfully.")
                return redirect("doctor_patient_record", patient_id=patient.id)
            except Exception as e:
                logger.error(f"Error adding medical record: {str(e)}")
                messages.error(request, "Failed to add medical record. Please try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = MedicalRecordForm()
    
    return render(request, "doctor/doctor_patient_record.html", {
        "patient": patient,
        "records": MedicalRecord.objects.filter(patient=patient).order_by("-uploaded_at"),
        "form": form
    })

@login_required
@role_required(["doctor"])
def delete_medical_record(request, record_id):
    """Delete a medical record."""
    record = get_object_or_404(MedicalRecord, id=record_id)
    patient_id = record.patient.id
    
    # Check if the current doctor owns this record
    if record.doctor != request.user.doctorprofile:
        messages.error(request, "You don't have permission to delete this record.")
        return redirect("doctor_patient_record", patient_id=patient_id)
    
    if request.method == "POST":
        try:
            record.delete()
            messages.success(request, "Medical record deleted successfully.")
        except Exception as e:
            logger.error(f"Error deleting medical record: {str(e)}")
            messages.error(request, "Failed to delete medical record. Please try again.")
    
    return redirect("doctor_patient_record", patient_id=patient_id)


@login_required
@role_required(["doctor"])
def doctor_patient_list(request):
    """Display list of patients for doctor to select from."""
    # Get all patients that this doctor has treated
    patients = PatientProfile.objects.filter(
        appointment__doctor=request.user.doctor_profile
    ).distinct()

    context = {
        'patients': patients
    }
    return render(request, "doctor/doctor_patient_list.html", context)


# *************************************************************************
#                         USER MANAGEMENT VIEWS (ADMIN)
# *************************************************************************

@login_required
@role_required(["admin"])
def user_management(request):
    """Admin view for user management with filtering."""
    users = User.objects.all().order_by('-date_joined')

    role_filter = request.GET.get('role')
    status_filter = request.GET.get('status')
    search_query = request.GET.get('q')

    if role_filter:
        users = users.filter(role=role_filter)
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'blocked':
        users = users.filter(is_active=False)
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone_number__icontains=search_query)
        )

    stats = {
        'total': users.count(),
        'doctors': users.filter(role='doctor').count(),
        'patients': users.filter(role='patient').count(),
        'admins': users.filter(role='admin').count(),
    }

    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'stats': stats,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'search_query': search_query,
    }
    return render(request, "admin/user_management.html", context)


@login_required
@role_required(["admin"])
def view_user(request, id):
    """Admin view for detailed user information."""
    user = get_object_or_404(User, pk=id)

    context = {
        "user_profile": user,
        "appointment_count": user.appointments.count() if hasattr(user, "appointments") else 0,
        "last_login": user.last_login,
        "date_joined": user.date_joined,
        'is_online': user.is_online() if hasattr(user, 'is_online') else False,
    }
    return render(request, "admin/view_user.html", context)


@login_required
@role_required(["admin"])
def edit_user(request, user_id):
    """Admin view for editing user information."""
    user = get_object_or_404(User, pk=user_id)

    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, "You cannot edit superuser accounts!")
        return redirect('user_management')

    if request.method == 'POST':
        profile_pic = request.FILES.get('profile_pic')
        if profile_pic:
            user.profile_pic = profile_pic

        user.first_name = request.POST.get('first_name')
        user.last_name = request.POST.get('last_name')
        user.email = request.POST.get('email')
        user.phone = request.POST.get('phone_number')
        user.role = request.POST.get('role')
        user.is_active = request.POST.get('is_active') == 'on'

        if request.POST.get('password'):
            user.set_password(request.POST.get('password'))
            messages.warning(request, "Password was updated for this user")

        if user.role == 'doctor':
            user.specialization = request.POST.get('specialization')
            user.license_number = request.POST.get('license_number')
            user.qualifications = request.POST.get('qualifications')
            user.consultation_fee = request.POST.get('consultation_fee')
            user.experience_years = request.POST.get('experience_years')

        try:
            user.save()
            messages.success(
                request, f"User {user.get_full_name()} updated successfully!")
            logger.info(f"User {user.id} edited by admin {request.user.id}")
            return redirect('view_user', user_id=user.id)
        except Exception as e:
            messages.error(request, f"Error saving user: {str(e)}")

    context = {
        'user': user,
        'is_doctor': user.role == 'doctor',
        'roles': User.ROLE_CHOICES
    }

    return render(request, 'admin/edit_user.html', context)


@login_required
@role_required(["admin"])
def toggle_user_status(request, id):
    """Handle user activation/deactivation."""
    try:
        user = get_object_or_404(User, pk=id)

        if request.user.id == user.id:
            logger.warning(
                f"Admin {request.user} attempted to block themselves")
            messages.error(request, "You cannot block your own account!")
            return redirect('user_management')

        old_status = user.is_active
        new_status = not old_status

        user.is_active = new_status
        user.save()

        action = "activated" if new_status else 'blocked'
        logger.info(f"User {user.id} {action} by admin {request.user.id}")

        if not new_status:
            send_email_status(user)

        if new_status:
            messages.success(
                request, f"Successfully activated user: {user.get_full_name()}")
        else:
            messages.warning(
                request, f"User {user.get_full_name()} has been blocked. Notification sent.")

        return redirect("view_user", id=id)

    except Exception as e:
        logger.error(f"Error fetching user with id {id}: {e}")
        messages.error(request, "User not found.")
        return redirect("user_management")


def send_email_status(user):
    """Send account status notification email."""
    subject = "MediTrack Account Status Update"
    message = f"""Dear {user.get_full_name()},
Your account status has been updated:
Status: {'Active' if user.is_active else 'Inactive'}

""" + (
        "Your account has been reactivated. You can now access all features."
        if user.is_active else
        "Your account has been temporarily suspended. Please contact admin for assistance."
    )

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )


@login_required
@role_required(["admin"])
def add_user(request):
    """Admin view to add new users."""
    if request.method == 'POST':
        form = AddUserForm(request.POST, request.FILES)
        try:
            if form.is_valid():
                with transaction.atomic():
                    user = form.save(commit=False)

                    if user.role == 'admin' and not form.cleaned_data.get('admin_code'):
                        form.add_error('admin_code', 'Admin code is required')
                        raise forms.ValidationError("Validation error")

                    user.save()

                    if user.role == 'doctor':
                        DoctorProfile.objects.create(
                            user=user,
                            specialization=form.cleaned_data['specialization'],
                            license_number=form.cleaned_data['license_number']
                        )
                    elif user.role == 'patient':
                        PatientProfile.objects.create(
                            user=user,
                            blood_group=form.cleaned_data.get(
                                'blood_group', '')
                        )
                    elif user.role == 'admin':
                        AdminProfile.objects.create(
                            user=user,
                            admin_code=form.cleaned_data['admin_code']
                        )

                    messages.success(
                        request, f'User {user.username} created successfully!')
                    return redirect('user_management')

        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
            logger.error(f"Error creating user: {str(e)}", exc_info=True)
    else:
        form = AddUserForm()

    context = {
        'form': form,
        'title': 'Add New User'
    }
    return render(request, 'admin/add_user.html', context)


# *************************************************************************
#                         ANNOUNCEMENT MANAGEMENT VIEWS
# *************************************************************************

@login_required
@role_required(["admin"])
def announcements(request):
    """Admin view for announcement management."""
    announcements_list = Announcement.objects.all().order_by('-created_at')

    status_filter = request.GET.get('status')
    priority_filter = request.GET.get('priority')
    search_query = request.GET.get('q')

    if status_filter == 'active':
        announcements_list = announcements_list.filter(is_active=True)
    elif status_filter == 'inactive':
        announcements_list = announcements_list.filter(is_active=False)

    if priority_filter:
        announcements_list = announcements_list.filter(
            priority=priority_filter)

    if search_query:
        announcements_list = announcements_list.filter(
            Q(title__icontains=search_query) |
            Q(content__icontains=search_query)
        )

    paginator = Paginator(announcements_list, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'priority_choices': Announcement.PRIORITY_CHOICES,
    }
    return render(request, "admin/announcements.html", context)


@login_required
@role_required(["admin"])
def create_announcements(request):
    """Admin view to create announcements."""
    if request.method == 'POST':
        form = AnnouncementForm(request.POST, request=request)
        if form.is_valid():
            announcement = form.save()
            messages.success(request, 'Announcement created successfully!')
            return redirect('announcements')
    else:
        form = AnnouncementForm(request=request)

    context = {
        'form': form,
        'title': 'Create New Announcement'
    }
    return render(request, 'admin/create_announcements.html', context)


@login_required
@role_required(["admin"])
def edit_announcement(request, pk):
    """Admin view to edit announcements."""
    announcement = get_object_or_404(Announcement, pk=pk)

    if request.method == 'POST':
        form = AnnouncementForm(
            request.POST, instance=announcement, request=request)
        if form.is_valid():
            form.save()
            messages.success(request, 'Announcement updated successfully!')
            return redirect('announcements')
    else:
        form = AnnouncementForm(instance=announcement, request=request)

    context = {
        'form': form,
        'title': 'Edit Announcement',
        'announcement': announcement
    }
    return render(request, 'admin/edit_announcement.html', context)


@login_required
@role_required(["admin"])
def toggle_announcement(request, pk):
    """Toggle announcement active status."""
    announcement = get_object_or_404(Announcement, pk=pk)
    if request.method == 'POST':
        announcement.is_active = not announcement.is_active
        announcement.save()
        status = "activated" if announcement.is_active else "deactivated"
        messages.success(request, f'Announcement {status} successfully!')
    return redirect('announcements')


@login_required
@role_required(["admin"])
def delete_announcement(request, pk):
    """Delete announcement."""
    announcement = get_object_or_404(Announcement, pk=pk)
    if request.method == 'POST':
        announcement.delete()
        messages.success(request, 'Announcement deleted successfully!')
    return redirect('announcements')


# *************************************************************************
#                         ACTIVITY LOG VIEWS
# *************************************************************************

@login_required
@role_required(["admin"])
def activity_logs(request):
    """Admin view for activity logs with filtering."""
    logs = ActivityLog.objects.all().select_related('user')

    filter_form = ActivityLogFilterForm(request.GET or None)

    if filter_form.is_valid():
        action = filter_form.cleaned_data.get('action')
        user = filter_form.cleaned_data.get('user')
        date_from = filter_form.cleaned_data.get('date_from')
        date_to = filter_form.cleaned_data.get('date_to')
        search = filter_form.cleaned_data.get('search')

        if action:
            logs = logs.filter(action=action)
        if user:
            logs = logs.filter(user=user)
        if date_from:
            logs = logs.filter(created_at__date__gte=date_from)
        if date_to:
            logs = logs.filter(created_at__date__lte=date_to)
        if search:
            logs = logs.filter(
                Q(user__username__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(details__icontains=search)
            )

    total_logs = logs.count()
    today_logs = logs.filter(created_at__date=timezone.now().date()).count()
    unique_users = logs.values('user').distinct().count()

    if total_logs > 0 and logs.exists():
        first_log_date = logs.earliest('created_at').created_at.date()
        days_diff = (timezone.now().date() - first_log_date).days
        days_diff = max(days_diff, 1)
        avg_daily_logs = round(total_logs / days_diff)
    else:
        avg_daily_logs = 0

    activity_distribution = logs.values('action').annotate(
        count=Count('action')
    ).order_by('-count')[:10]

    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'total_logs': total_logs,
        'today_logs': today_logs,
        'unique_users': unique_users,
        'avg_daily_logs': avg_daily_logs,
        'activity_distribution': activity_distribution,
    }
    return render(request, 'admin/activity_logs.html', context)


@login_required
@role_required(["admin"])
def activity_log_details(request, log_id):
    """View detailed activity log information."""
    log = get_object_or_404(ActivityLog, id=log_id)

    context = {
        'log': log,
        'title': 'Activity Log Details'
    }
    return render(request, 'admin/activity_log_details.html', context)


@login_required
@role_required(["admin"])
def export_activity_logs(request):
    """Export activity logs as CSV."""
    logs = ActivityLog.objects.all().select_related('user')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="activity_logs_export.csv"'

    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'User', 'Action', 'Model',
                    'Object ID', 'IP Address', 'Details'])

    for log in logs:
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.user.get_full_name() if log.user else 'System',
            log.get_action_display(),
            log.model_name,
            log.object_id,
            log.ip_address,
            json.dumps(log.details, ensure_ascii=False)
        ])

    return response


@login_required
@role_required(["admin"])
def clear_activity_logs(request):
    """Clear old activity logs."""
    if request.method == 'POST':
        cutoff_date = timezone.now() - timedelta(days=90)
        deleted_count, _ = ActivityLog.objects.filter(
            created_at__lt=cutoff_date).delete()

        messages.success(
            request, f'Cleared {deleted_count} old activity logs (older than 90 days).')
        return redirect('activity_logs')

    cutoff_date = timezone.now() - timedelta(days=90)
    logs_to_delete = ActivityLog.objects.filter(
        created_at__lt=cutoff_date).count()
    total_logs = ActivityLog.objects.count()

    context = {
        'logs_to_delete': logs_to_delete,
        'total_logs': total_logs,
        'cutoff_date': cutoff_date,
    }
    return render(request, 'admin/clear_activity_logs.html', context)


# *************************************************************************
#                         REPORTING VIEWS
# *************************************************************************

@login_required
@role_required(["admin"])
def reports_analytics(request):
    """Reports and analytics dashboard."""
    recent_reports = SystemReport.objects.filter(
        generated_by=request.user).order_by('-generated_at')[:10]

    stats = {
        'total_users': User.objects.count(),
        'active_users': User.objects.filter(is_active=True).count(),
        'total_appointments': Appointment.objects.count(),
        'today_appointments': Appointment.objects.filter(date=timezone.now().date()).count(),
        'total_prescriptions': Prescription.objects.count(),
    }

    context = {
        'recent_reports': recent_reports,
        'stats': stats,
    }
    return render(request, 'admin/reports_analytics.html', context)


@login_required
@role_required(["admin"])
def generate_report(request):
    """Generate system reports."""
    if request.method == 'POST':
        form = SystemReportForm(request.POST)
        if form.is_valid():
            try:
                report_type = form.cleaned_data['report_type']
                format = form.cleaned_data['format']

                if report_type == 'user':
                    response = ReportGenerator.generate_user_report(format)
                    title = f"User Report - {timezone.now().strftime('%Y-%m-%d')}"
                elif report_type == 'appointment':
                    response = ReportGenerator.generate_appointment_report(
                        form.cleaned_data['start_date'],
                        form.cleaned_data['end_date'],
                        format
                    )
                    title = f"Appointment Report ({form.cleaned_data['start_date']} to {form.cleaned_data['end_date']})"
                elif report_type == 'prescription':
                    response = ReportGenerator.generate_prescription_report(
                        form.cleaned_data['doctor'].id if form.cleaned_data['doctor'] else None,
                        format
                    )
                    title = f"Prescription Report - {timezone.now().strftime('%Y-%m-%d')}"

                if 'save_report' in request.POST:
                    report = SystemReport(
                        title=title,
                        report_type=report_type,
                        format=format,
                        generated_by=request.user,
                        parameters={
                            'start_date': str(form.cleaned_data.get('start_date', '')),
                            'end_date': str(form.cleaned_data.get('end_date', '')),
                            'doctor_id': form.cleaned_data.get('doctor').id if form.cleaned_data.get('doctor') else None
                        }
                    )

                    if format == 'csv':
                        file_content = response.content
                        report.file.save(
                            f"{report_type}_report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv", io.BytesIO(file_content))
                    elif format == 'pdf':
                        file_content = response.content
                        report.file.save(
                            f"{report_type}_report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf", io.BytesIO(file_content))

                    report.save()
                    messages.success(
                        request, f"Report '{title}' has been saved successfully!")
                    return redirect('reports_analytics')

                return response

            except Exception as e:
                messages.error(request, f"Error generating report: {str(e)}")
                logger.error(
                    f"Error generating report: {str(e)}", exc_info=True)
    else:
        form = SystemReportForm()

    context = {
        'form': form,
        'title': 'Generate Report'
    }
    return render(request, 'admin/generate_report.html', context)


@login_required
@role_required(["admin"])
def view_report(request, report_id):
    """View saved reports."""
    report = get_object_or_404(SystemReport, id=report_id)

    if not os.path.exists(report.file.path):
        messages.error(request, "Report file not found!")
        return redirect('reports_analytics')

    if report.format == 'pdf':
        with open(report.file.path, 'rb') as pdf:
            response = HttpResponse(pdf.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{os.path.basename(report.file.path)}"'
            return response
    elif report.format == 'csv':
        with open(report.file.path, 'rb') as csv_file:
            response = HttpResponse(csv_file.read(), content_type='text/csv')
            response[
                'Content-Disposition'] = f'attachment; filename="{os.path.basename(report.file.path)}"'
            return response

    messages.error(request, "Unsupported report format")
    return redirect('reports_analytics')


@login_required
@role_required(["admin"])
def delete_report(request, report_id):
    """Delete saved reports."""
    report = get_object_or_404(SystemReport, id=report_id)
    if request.method == 'POST':
        try:
            report.delete()
            messages.success(request, "Report deleted successfully!")
        except Exception as e:
            messages.error(request, f"Error deleting report: {str(e)}")
    return redirect('reports_analytics')


# *************************************************************************
#                         EXPORT VIEWS
# *************************************************************************

@login_required
@role_required(["admin"])
def export_appointments(request):
    """Export appointments as CSV."""
    appointments = Appointment.objects.all().order_by('-date', '-time')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="appointments_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Patient', 'Doctor', 'Date', 'Time',
        'Status', 'Reason', 'Symptoms', 'Created At'
    ])

    for appt in appointments:
        writer.writerow([
            appt.id,
            appt.patient.user.get_full_name(),
            appt.doctor.user.get_full_name(),
            appt.date.strftime('%Y-%m-%d'),
            appt.time.strftime('%H:%M'),
            appt.get_status_display(),
            appt.get_reason_display(),
            appt.symptoms,
            appt.created_at.strftime('%Y-%m-%d %H:%M'),
        ])

    return response


@login_required
@role_required(["admin"])
def export_users_csv(request):
    """Export users as CSV."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users_export.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Username', 'Full Name', 'Email',
                    'Phone', 'Role', 'Status', 'Join Date', 'Last Login'])

    users = User.objects.all()
    for user in users:
        writer.writerow([
            user.id,
            user.username,
            user.get_full_name(),
            user.email,
            user.phone_number or '',
            user.get_role_display(),
            'Active' if user.is_active else 'Blocked',
            user.date_joined.strftime('%Y-%m-%d %H:%M'),
            user.last_login.strftime(
                '%Y-%m-%d %H:%M') if user.last_login else 'Never'
        ])

    return response


# *************************************************************************
#                         SYSTEM SETTINGS VIEWS
# *************************************************************************

@login_required
@role_required(["admin"])
def system_settings(request):
    """System settings management view."""
    categories = SystemSetting.CATEGORIES
    selected_category = request.GET.get('category', 'general')

    settings = SystemSetting.objects.filter(
        category=selected_category).order_by('order')
    setting_forms = {}

    if request.method == 'POST':
        for setting in settings:
            form = SystemSettingForm(
                request.POST, prefix=setting.key, instance=setting)
            if form.is_valid():
                setting_instance = form.save(commit=False)
                setting_instance.set_value(form.cleaned_data['value'])
                setting_instance.save()
                messages.success(
                    request, f'Setting {setting.label} updated successfully!')
            setting_forms[setting.key] = form
    else:
        for setting in settings:
            setting_forms[setting.key] = SystemSettingForm(
                prefix=setting.key, instance=setting)

    system_stats = {
        'total_users': User.objects.count(),
        'total_appointments': Appointment.objects.count(),
        'total_prescriptions': Prescription.objects.count(),
        'total_logs': ActivityLog.objects.count(),
        'db_size': get_database_size(),
        'media_size': get_media_folder_size(),
    }

    context = {
        'categories': categories,
        'selected_category': selected_category,
        'setting_forms': setting_forms,
        'system_stats': system_stats,
    }
    return render(request, 'admin/system_settings.html', context)


@login_required
@role_required(["admin"])
def backup_management(request):
    """Backup management view."""
    backup_form = BackupForm()
    backup_logs = BackupLog.objects.all().order_by('-created_at')[:10]

    if request.method == 'POST':
        backup_form = BackupForm(request.POST)
        if backup_form.is_valid():
            try:
                backup_log = BackupLog.objects.create(
                    backup_type=backup_form.cleaned_data['backup_type'],
                    filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    status='pending',
                    created_by=request.user,
                    notes=backup_form.cleaned_data['notes']
                )

                messages.success(
                    request, 'Backup process started successfully!')
                return redirect('backup_management')

            except Exception as e:
                messages.error(request, f'Backup failed: {str(e)}')

    context = {
        'backup_form': backup_form,
        'backup_logs': backup_logs,
    }
    return render(request, 'admin/backup_management.html', context)


@login_required
@role_required(["admin"])
def maintenance_tools(request):
    """System maintenance tools view."""
    maintenance_form = MaintenanceForm()
    maintenance_logs = MaintenanceLog.objects.all().order_by(
        '-started_at')[:10]

    if request.method == 'POST':
        maintenance_form = MaintenanceForm(request.POST)
        if maintenance_form.is_valid():
            maintenance_type = maintenance_form.cleaned_data['maintenance_type']

            try:
                if maintenance_type == 'cleanup_logs':
                    cutoff_date = timezone.now() - timedelta(days=90)
                    deleted_count, _ = ActivityLog.objects.filter(
                        created_at__lt=cutoff_date).delete()

                    MaintenanceLog.objects.create(
                        maintenance_type='cleanup',
                        description=f'Cleaned up {deleted_count} activity logs older than 90 days',
                        status='success',
                        affected_records=deleted_count,
                        initiated_by=request.user
                    )
                    messages.success(
                        request, f'Cleaned up {deleted_count} old activity logs!')

                elif maintenance_type == 'optimize_db':
                    with connection.cursor() as cursor:
                        cursor.execute("VACUUM ANALYZE")

                    MaintenanceLog.objects.create(
                        maintenance_type='database',
                        description='Database optimization performed',
                        status='success',
                        initiated_by=request.user
                    )
                    messages.success(
                        request, 'Database optimization completed!')

                elif maintenance_type == 'clear_cache':
                    cache.clear()

                    MaintenanceLog.objects.create(
                        maintenance_type='system',
                        description='System cache cleared',
                        status='success',
                        initiated_by=request.user
                    )
                    messages.success(
                        request, 'System cache cleared successfully!')

                return redirect('maintenance_tools')

            except Exception as e:
                messages.error(
                    request, f'Maintenance operation failed: {str(e)}')

    context = {
        'maintenance_form': maintenance_form,
        'maintenance_logs': maintenance_logs,
    }
    return render(request, 'admin/maintenance_tools.html', context)


@login_required
@role_required(["admin"])
def system_status(request):
    """System status and health monitoring view."""
    health_checks = {
        'database': check_database_connection(),
        'storage': check_storage_space(),
        'cache': check_cache_status(),
        'background_tasks': check_background_tasks(),
    }

    recent_activities = ActivityLog.objects.all().order_by('-created_at')[:10]

    system_metrics = {
        'uptime': get_system_uptime(),
        'memory_usage': get_memory_usage(),
        'cpu_usage': get_cpu_usage(),
    }

    context = {
        'health_checks': health_checks,
        'recent_activities': recent_activities,
        'system_metrics': system_metrics,
    }
    return render(request, 'admin/system_status.html', context)


# *************************************************************************
#                         SIMPLE REDIRECT VIEWS
# *************************************************************************

@login_required
@role_required(["patient"])
def find_doctor(request):
    """Patient view to find and search doctors."""
    doctors = DoctorProfile.objects.filter(user__is_active=True)

    # Add filtering
    specialization_filter = request.GET.get('specialization')
    city_filter = request.GET.get('city')
    search_query = request.GET.get('q')

    if specialization_filter:
        doctors = doctors.filter(specialization=specialization_filter)

    if city_filter:
        doctors = doctors.filter(city__icontains=city_filter)

    if search_query:
        doctors = doctors.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(specialization__icontains=search_query) |
            Q(qualifications__icontains=search_query)
        )

    # Get unique specializations for filter dropdown
    specializations = DoctorProfile.objects.values_list(
        'specialization', flat=True
    ).distinct().exclude(specialization__isnull=True).exclude(specialization='')

    paginator = Paginator(doctors, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'specializations': specializations,
        'specialization_filter': specialization_filter,
        'city_filter': city_filter,
        'search_query': search_query
    }
    return render(request, 'patient/find_doctor.html', context)


def get_available_time_slots(start_time, end_time, slot_duration, booked_slots):
    """
    start_time, end_time => datetime.time objects
    slot_duration => minutes (int)
    booked_slots => list of strings in '%H:%M' format
    """
    slots = []
    current_time = datetime.combine(datetime.today(), start_time)

    while current_time.time() < end_time:
        slot_str = current_time.strftime("%H:%M")
        if slot_str not in booked_slots:
            slots.append(slot_str)
        current_time += timedelta(minutes=slot_duration)

    return slots


@login_required
@role_required(["patient"])
def doctor_detail(request, doctor_id):
    """Patient view of doctor details."""
    doctor = get_object_or_404(
        DoctorProfile, id=doctor_id, user__is_active=True)

    # Get available time slots for booking
    # available_slots = get_available_time_slots(
    #     doctor, timezone.now().date() + timedelta(days=1))

    context = {
        'doctor': doctor,
        # 'available_slots': available_slots
    }
    return render(request, 'patient/doctor_detail.html', context)


@login_required
@role_required(["doctor"])
def doctor_create_prescription(request):
    """Doctor prescription creation view."""
    return render(request, "doctor_create_prescription.html")


@login_required
@role_required(["doctor"])
def doctor_schedule(request):
    """Doctor schedule management view."""
    doctor_profile = request.user.doctor_profile
    today = timezone.now().date()

    # Get appointments
    appointments = Appointment.objects.filter(
        doctor=doctor_profile,
        date__gte=today
    ).order_by('date', 'time')

    # Get upcoming appointments (next 7 days)
    upcoming_appointments = appointments.filter(
        date__lte=today + timedelta(days=7)
    )

    # Calculate statistics
    available_slots_week = calculate_available_slots(
        doctor_profile, today, today + timedelta(days=7))
    busy_slots = appointments.filter(
        date__gte=today, date__lte=today + timedelta(days=7)).count()

    context = {
        'doctor_profile': doctor_profile,
        'appointments': appointments,
        'upcoming_appointments': upcoming_appointments,
        'today_appointments': appointments.filter(date=today),
        'available_slots_week': available_slots_week,
        'busy_slots': busy_slots,
        'time_off_count': 0,  # You can implement time-off functionality later
        'days_of_week': [
            (0, 'Sunday'), (1, 'Monday'), (2, 'Tuesday'),
            (3, 'Wednesday'), (4, 'Thursday'), (5, 'Friday'), (6, 'Saturday')
        ]
    }

    return render(request, "doctor/doctor_schedule.html", context)


def calculate_available_slots(doctor_profile, start_date, end_date):
    """Calculate available time slots for a given date range."""
    available_days = doctor_profile.available_days or [1, 2, 3, 4, 5]

    slots_raw = doctor_profile.available_time_slots
    if isinstance(slots_raw, str):
        try:
            # yahan ['10:00:00', '14:00:00'] milega
            available_slots = json.loads(slots_raw)
        except Exception as e:
            print("JSON decode error:", e)
            available_slots = ["09:00:00"]
    else:
        available_slots = slots_raw or ["09:00:00"]

    print("DEBUG parsed slots:", available_slots)

    business_days = 0
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() in available_days:
            business_days += 1
        current_date += timedelta(days=1)

    total_slots = 0
    for slot in available_slots:
        print("DEBUG slot:", slot, "| type:", type(slot))
        # slot is a string like "10:00:00"
        start = datetime.strptime(slot, "%H:%M:%S").time()
        # Default assumption: each slot = 1 hour = 4 appointments of 15 min
        total_slots += 4 * business_days

    return total_slots


@login_required
@role_required(["doctor"])
def availability_update(request):
    """Doctor availability management view."""
    doctor_profile = request.user.doctor_profile

    if request.method == 'POST':
        form = DoctorAvailabilityForm(request.POST, instance=doctor_profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Availability updated successfully!')
            return redirect('doctor_dashboard')
    else:
        form = DoctorAvailabilityForm(instance=doctor_profile)

    return render(request, 'doctor/availability_update.html', {'form': form})


# Doctor Calendar View
@login_required
@role_required(["doctor"])
def doctor_calendar(request):
    if request.user.role != 'doctor':   # sirf doctor access kar sake
        return redirect('dashboard')

    appointments = Appointment.objects.filter(
        doctor=request.user).order_by('date', 'time')

    context = {
        'appointments': appointments
    }
    return render(request, 'doctor_calendar.html', context)


@login_required
@role_required(["doctor"])
def appointment_calendar_view(request):
    if request.user.role != 'doctor':   # sirf doctor access kar sake
        return redirect('dashboard')

    appointments = Appointment.objects.filter(
        doctor=request.user).order_by('date', 'time')

    context = {
        'appointments': appointments
    }
    return render(request, 'appointment_calendar_view.html', context)


@login_required
@role_required(['patient'])
def medical_records(request):
    """Patient medical records view."""
    return render(request, "medical_records.html")


@login_required
@role_required(["patient"])
def appointment_history(request):
    """Patient appointment history view."""
    appointments = Appointment.objects.filter(
        patient=request.user.patient_profile
    ).order_by('-date', '-time')

    # Add filtering
    status_filter = request.GET.get('status')
    if status_filter:
        appointments = appointments.filter(status=status_filter)

    paginator = Paginator(appointments, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'status_filter': status_filter
    }
    return render(request, 'patient/appointment_history.html', context)


@login_required
@role_required(["patient"])
def medical_records(request):
    """Patient medical records view."""
    records = MedicalRecord.objects.filter(
        patient=request.user.patient_profile
    ).order_by('-uploaded_at')

    context = {
        'records': records
    }
    return render(request, 'patient/medical_records.html', context)


@login_required
@role_required(['patient'])
def appointment_create(request):
    """Patient appointment history view."""
    return render(request, "appointment_create.html")


@login_required
@role_required(["admin"])
def reports_dashboard(request):
    """Reports dashboard with various metrics and charts."""
    # User statistics
    user_stats = {
        'total': User.objects.count(),
        'doctors': User.objects.filter(role='doctor', is_active=True).count(),
        'patients': User.objects.filter(role='patient', is_active=True).count(),
        'new_today': User.objects.filter(date_joined__date=timezone.now().date()).count(),
        'new_week': User.objects.filter(date_joined__date__gte=timezone.now().date() - timedelta(days=7)).count(),
    }

    # Appointment statistics
    appointment_stats = {
        'total': Appointment.objects.count(),
        'completed': Appointment.objects.filter(status='completed').count(),
        'pending': Appointment.objects.filter(status='pending').count(),
        'cancelled': Appointment.objects.filter(status='cancelled').count(),
        'today': Appointment.objects.filter(date=timezone.now().date()).count(),
    }

    # Revenue statistics (if applicable)
    revenue_stats = {
        'total': Appointment.objects.filter(status='completed').aggregate(
            total=Sum('doctor__consultation_fee')
        )['total'] or 0,
        'month': Appointment.objects.filter(
            status='completed',
            date__month=timezone.now().month,
            date__year=timezone.now().year
        ).aggregate(total=Sum('doctor__consultation_fee'))['total'] or 0,
        'week': Appointment.objects.filter(
            status='completed',
            date__gte=timezone.now().date() - timedelta(days=7)
        ).aggregate(total=Sum('doctor__consultation_fee'))['total'] or 0,
    }

    # Recent activities
    recent_activities = ActivityLog.objects.all().order_by('-created_at')[:10]

    context = {
        'user_stats': user_stats,
        'appointment_stats': appointment_stats,
        'revenue_stats': revenue_stats,
        'recent_activities': recent_activities,
    }
    return render(request, 'admin/reports_dashboard.html', context)


# *************************************************************************
#                         UTILITY FUNCTIONS
# *************************************************************************

def get_database_size():
    """Get approximate database size."""
    try:
        with connection.cursor() as cursor:
            if connection.vendor == 'postgresql':
                cursor.execute("SELECT pg_database_size(current_database())")
                size_bytes = cursor.fetchone()[0]
            elif connection.vendor == 'mysql':
                cursor.execute(
                    "SELECT SUM(data_length + index_length) FROM information_schema.tables WHERE table_schema = DATABASE()")
                size_bytes = cursor.fetchone()[0]
            else:
                cursor.execute(
                    "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
                size_bytes = cursor.fetchone()[0]

        return size_bytes
    except:
        return 0


def get_media_folder_size():
    """Get media folder size."""
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(settings.MEDIA_ROOT):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
        return total_size
    except:
        return 0


def check_database_connection():
    """Check database connection status."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return {'status': 'healthy', 'message': 'Database connection successful'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def check_storage_space():
    """Check storage space availability."""
    try:
        stat = os.statvfs(settings.BASE_DIR)
        free_space = stat.f_frsize * stat.f_bavail
        total_space = stat.f_frsize * stat.f_blocks
        percent_used = (1 - (free_space / total_space)) * 100

        if percent_used > 90:
            status = 'warning'
        elif percent_used > 95:
            status = 'error'
        else:
            status = 'healthy'

        return {
            'status': status,
            'message': f'{percent_used:.1f}% storage used',
            'free_space': free_space,
            'total_space': total_space
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def check_cache_status():
    """Check if cache is working properly."""
    try:
        test_key = 'cache_test_key'
        test_value = 'cache_test_value'

        cache.set(test_key, test_value, timeout=60)
        retrieved_value = cache.get(test_key)

        if retrieved_value == test_value:
            return {'status': 'healthy', 'message': 'Cache is working properly'}
        else:
            return {'status': 'error', 'message': 'Cache retrieval failed'}

    except Exception as e:
        return {'status': 'error', 'message': f'Cache error: {str(e)}'}


def check_background_tasks():
    """Check background tasks status."""
    try:
        return {'status': 'healthy', 'message': 'Background tasks monitoring not configured'}
    except Exception as e:
        return {'status': 'error', 'message': f'Background tasks error: {str(e)}'}


def get_system_uptime():
    """Get system uptime in human readable format."""
    try:
        if hasattr(psutil, 'boot_time'):
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            return format_timespan(uptime_seconds)
        else:
            return "N/A"
    except:
        return "N/A"


def get_memory_usage():
    """Get memory usage statistics."""
    try:
        memory = psutil.virtual_memory()
        return {
            'total': memory.total,
            'used': memory.used,
            'free': memory.free,
            'percent': memory.percent
        }
    except:
        return {'total': 0, 'used': 0, 'free': 0, 'percent': 0}


def get_cpu_usage():
    """Get CPU usage percentage."""
    try:
        return psutil.cpu_percent(interval=1)
    except:
        return 0


def format_timespan(seconds):
    """Convert seconds to human readable format."""
    intervals = (
        ('weeks', 604800),
        ('days', 86400),
        ('hours', 3600),
        ('minutes', 60),
        ('seconds', 1),
    )

    result = []
    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            result.append(f"{int(value)} {name}")

    return ', '.join(result[:2]) if result else '0 seconds'
