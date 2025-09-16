import os
import json
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from phonenumber_field.modelfields import PhoneNumberField
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings


def validate_file_extension(value):
    """Validate that uploaded files have allowed extensions."""
    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
    if ext not in valid_extensions:
        raise ValidationError(
            _('Unsupported file extension. Allowed extensions: %(valid_extensions)s'),
            params={'valid_extensions': ', '.join(valid_extensions)}
        )


def validate_file_size(value):
    """Validate that uploaded files don't exceed maximum size."""
    max_size = 5 * 1024 * 1024  # 5MB
    if value.size > max_size:
        raise ValidationError(
            _('File size must be no more than %(max_size)s MB'),
            params={'max_size': max_size // (1024 * 1024)}
        )


class User(AbstractUser):
    """Custom User model with additional fields and role-based functionality."""
    
    class RoleChoices(models.TextChoices):
        ADMIN = "admin", _("Admin")
        PATIENT = "patient", _("Patient")
        DOCTOR = "doctor", _("Doctor")

    class GenderChoices(models.TextChoices):
        MALE = "M", _("Male")
        FEMALE = "F", _("Female")
        OTHER = "O", _("Other")
        PREFER_NOT_TO_SAY = "P", _("Prefer not to say")

    # Personal Information
    phone_number = PhoneNumberField(region="PK", blank=True, verbose_name=_("Phone Number"))
    gender = models.CharField(
        max_length=1, 
        choices=GenderChoices.choices, 
        blank=True,
        verbose_name=_("Gender")
    )
    date_of_birth = models.DateField(
        null=True, 
        blank=True,
        verbose_name=_("Date of Birth")
    )
    profile_pic = models.ImageField(
        upload_to="profile_pics/%Y/%m/%d/",
        validators=[validate_file_extension, validate_file_size],
        blank=True, 
        null=True,
        verbose_name=_("Profile Picture")
    )
    
    # Role and Status
    role = models.CharField(
        max_length=10, 
        choices=RoleChoices.choices, 
        default=RoleChoices.PATIENT,
        verbose_name=_("Role")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active Status")
    )
    email_verified = models.BooleanField(
        default=False,
        verbose_name=_("Email Verified")
    )
    last_activity = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Activity")
    )

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['role']),
            models.Index(fields=['is_active']),
            models.Index(fields=['date_joined']),
        ]

    def clean(self):
        """Validate model data before saving."""
        super().clean()
        
        # Validate date of birth is not in future
        if self.date_of_birth and self.date_of_birth > timezone.now().date():
            raise ValidationError({
                'date_of_birth': _("Date of birth cannot be in the future.")
            })
        
        # Validate admin role requires admin profile
        if self.role == self.RoleChoices.ADMIN and not hasattr(self, 'admin_profile'):
            raise ValidationError({
                'role': _("Admin users must have an admin profile.")
            })

    def save(self, *args, **kwargs):
        """Override save method to ensure validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def is_online(self):
        """Check if user is currently online (active within last 15 minutes)."""
        if self.last_activity:
            return (timezone.now() - self.last_activity).total_seconds() < 900  # 15 minutes
        return False

    @property
    def age(self):
        """Calculate user's age based on date of birth."""
        if self.date_of_birth:
            today = timezone.now().date()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None


class AdminProfile(models.Model):
    """Profile for admin users with additional admin-specific fields."""
    
    user = models.OneToOneField(
        User, 
        related_name="admin_profile", 
        on_delete=models.CASCADE,
        verbose_name=_("User")
    )
    admin_code = models.CharField(
        max_length=50, 
        unique=True,
        verbose_name=_("Admin Code")
    )
    department = models.CharField(
        max_length=100, 
        blank=True,
        verbose_name=_("Department")
    )
    permissions = models.JSONField(
        default=list,
        verbose_name=_("Permissions")
    )

    class Meta:
        verbose_name = _("Admin Profile")
        verbose_name_plural = _("Admin Profiles")

    def __str__(self):
        return f"Admin: {self.user.username} ({self.department or 'No Department'})"


class DoctorProfile(models.Model):
    """Profile for doctor users with professional information."""
    
    user = models.OneToOneField(
        User, 
        related_name="doctor_profile", 
        on_delete=models.CASCADE,
        verbose_name=_("User")
    )
    specialization = models.CharField(
        max_length=100, 
        blank=True,
        verbose_name=_("Specialization")
    )
    hospital = models.CharField(
        max_length=100, 
        blank=True,
        verbose_name=_("Hospital")
    )
    city = models.CharField(
        max_length=100, 
        blank=True,
        verbose_name=_("City")
    )
    license_number = models.CharField(
        max_length=50, 
        unique=True, 
        blank=True, 
        null=True,
        verbose_name=_("License Number")
    )
    consultation_fee = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=2000.00,
        validators=[MinValueValidator(0)],
        verbose_name=_("Consultation Fee")
    )
    available_days = models.JSONField(
        default=list, 
        blank=True,
        verbose_name=_("Available Days")
    )
    available_time_slots = models.JSONField(
        default=list, 
        blank=True,
        verbose_name=_("Available Time Slots")
    )
    years_of_experience = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(50)],
        verbose_name=_("Years of Experience")
    )
    qualifications = models.TextField(
        blank=True,
        verbose_name=_("Qualifications")
    )
    bio = models.TextField(
        blank=True,
        verbose_name=_("Biography")
    )
    is_verified = models.BooleanField(
        default=False,
        verbose_name=_("Verified Doctor")
    )

    class Meta:
        verbose_name = _("Doctor Profile")
        verbose_name_plural = _("Doctor Profiles")
        indexes = [
            models.Index(fields=["specialization"]),
            models.Index(fields=["city"]),
            models.Index(fields=["is_verified"]),
        ]

    def __str__(self):
        full_name = self.user.get_full_name() or self.user.username
        return f"DR. {full_name} ({self.specialization or 'General Practitioner'})"

    @property
    def average_rating(self):
        """Calculate average rating from appointments."""
        from django.db.models import Avg
        return self.appointments.aggregate(
            avg_rating=Avg('rating')
        )['avg_rating'] or 0.0


class PatientProfile(models.Model):
    """Profile for patient users with medical information."""
    
    class BloodGroupChoices(models.TextChoices):
        A_POSITIVE = "A+", "A+"
        A_NEGATIVE = "A-", "A-"
        B_POSITIVE = "B+", "B+"
        B_NEGATIVE = "B-", "B-"
        AB_POSITIVE = "AB+", "AB+"
        AB_NEGATIVE = "AB-", "AB-"
        O_POSITIVE = "O+", "O+"
        O_NEGATIVE = "O-", "O-"

    user = models.OneToOneField(
        User, 
        related_name="patient_profile", 
        on_delete=models.CASCADE,
        verbose_name=_("User")
    )
    blood_group = models.CharField(
        max_length=3, 
        choices=BloodGroupChoices.choices,
        blank=True,
        verbose_name=_("Blood Group")
    )
    allergies = models.TextField(
        blank=True,
        verbose_name=_("Allergies")
    )
    medical_history = models.TextField(
        blank=True,
        verbose_name=_("Medical History")
    )
    emergency_contact = PhoneNumberField(
        region="PK", 
        blank=True,
        verbose_name=_("Emergency Contact")
    )
    emergency_contact_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Emergency Contact Name")
    )
    insurance_provider = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Insurance Provider")
    )
    insurance_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Insurance Number")
    )

    class Meta:
        verbose_name = _("Patient Profile")
        verbose_name_plural = _("Patient Profiles")

    def __str__(self):
        return f"Patient: {self.user.get_full_name() or self.user.username}"

    @property
    def has_insurance(self):
        """Check if patient has insurance information."""
        return bool(self.insurance_provider and self.insurance_number)


class MedicalRecord(models.Model):
    """Model for storing patient medical records."""
    
    class RecordTypeChoices(models.TextChoices):
        PRESCRIPTION = "prescription", _("Prescription")
        LAB_RESULT = "lab_result", _("Lab Result")
        IMAGING = "imaging", _("Imaging")
        DIAGNOSIS = "diagnosis", _("Diagnosis")
        TREATMENT = "treatment", _("Treatment Plan")
        OTHER = "other", _("Other")

    patient = models.ForeignKey(
        PatientProfile, 
        related_name="medical_records", 
        on_delete=models.CASCADE,
        verbose_name=_("Patient")
    )
    file = models.FileField(
        upload_to="medical_records/%Y/%m/%d/",
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "dicom"]),
            validate_file_size
        ],
        verbose_name=_("Medical File")
    )
    record_type = models.CharField(
        max_length=20, 
        choices=RecordTypeChoices.choices,
        default=RecordTypeChoices.OTHER,
        verbose_name=_("Record Type")
    )
    title = models.CharField(
        max_length=200,
        verbose_name=_("Record Title")
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Uploaded At")
    )
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_records",
        verbose_name=_("Uploaded By")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )
    is_shared = models.BooleanField(
        default=False,
        verbose_name=_("Shared with Patient")
    )

    class Meta:
        verbose_name = _("Medical Record")
        verbose_name_plural = _("Medical Records")
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=['patient', 'record_type']),
            models.Index(fields=['uploaded_at']),
        ]

    def __str__(self):
        return f"Medical Record: {self.title} for {self.patient.user.username}"

    @property
    def file_size(self):
        """Return human-readable file size."""
        if self.file:
            size_bytes = self.file.size
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024.0
        return "0 B"


class Appointment(models.Model):
    """Model for managing patient-doctor appointments."""
    
    class StatusChoices(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        CANCELLED = "cancelled", _("Cancelled")
        COMPLETED = "completed", _("Completed")
        NO_SHOW = "no_show", _("No Show")

    class ReasonChoices(models.TextChoices):
        CHECKUP = "CHECKUP", _("Routine Checkup")
        CONSULT = "CONSULT", _("General Consultation")
        FEVER = "FEVER", _("Fever/Infection")
        INJURY = "INJURY", _("Injury Treatment")
        FOLLOW_UP = "FOLLOW_UP", _("Follow-up Visit")
        EMERGENCY = "EMERGENCY", _("Emergency")
        OTHER = "OTHER", _("Other")

    patient = models.ForeignKey(
        PatientProfile, 
        on_delete=models.CASCADE,
        verbose_name=_("Patient")
    )
    doctor = models.ForeignKey(
        DoctorProfile, 
        on_delete=models.CASCADE,
        verbose_name=_("Doctor")
    )
    date = models.DateField(verbose_name=_("Appointment Date"))
    time = models.TimeField(verbose_name=_("Appointment Time"))
    status = models.CharField(
        max_length=20, 
        choices=StatusChoices.choices, 
        default=StatusChoices.PENDING,
        verbose_name=_("Status")
    )
    symptoms = models.TextField(
        blank=True,
        verbose_name=_("Symptoms")
    )
    reason = models.CharField(
        max_length=50, 
        choices=ReasonChoices.choices, 
        default=ReasonChoices.CONSULT,
        verbose_name=_("Reason")
    )
    other_reason = models.CharField(
        max_length=100, 
        blank=True,
        verbose_name=_("Other Reason")
    )
    cancellation_reason = models.TextField(
        blank=True, 
        null=True,
        verbose_name=_("Cancellation Reason")
    )
    cancelled_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='cancelled_appointments',
        verbose_name=_("Cancelled By")
    )
    end_time = models.TimeField(
        null=True, 
        blank=True,
        verbose_name=_("End Time")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )
    rating = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_("Patient Rating")
    )
    feedback = models.TextField(
        blank=True,
        verbose_name=_("Patient Feedback")
    )

    class Meta:
        verbose_name = _("Appointment")
        verbose_name_plural = _("Appointments")
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "date", "time"], 
                name="unique_doctor_slot"
            ),
        ]
        ordering = ["-date", "time"]
        indexes = [
            models.Index(fields=['doctor', 'date']),
            models.Index(fields=['patient', 'status']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Appointment: {self.patient.user.username} with DR. {self.doctor.user.username} on {self.date}"

    def clean(self):
        """Validate appointment data."""
        super().clean()
        
        # Validate appointment date is not in the past
        if self.date and self.date < timezone.now().date():
            raise ValidationError({
                'date': _("Appointment date cannot be in the past.")
            })
        
        # Validate end_time is after start time
        if self.end_time and self.time and self.end_time <= self.time:
            raise ValidationError({
                'end_time': _("End time must be after start time.")
            })

    @property
    def duration(self):
        """Calculate appointment duration in minutes."""
        if self.time and self.end_time:
            start_dt = timezone.datetime.combine(self.date, self.time)
            end_dt = timezone.datetime.combine(self.date, self.end_time)
            return (end_dt - start_dt).total_seconds() / 60
        return 30  # Default 30 minutes

    @property
    def is_upcoming(self):
        """Check if appointment is upcoming."""
        if self.date and self.time:
            appointment_dt = timezone.datetime.combine(self.date, self.time)
            return appointment_dt > timezone.now()
        return False


class Prescription(models.Model):
    """Model for doctor prescriptions."""
    
    appointment = models.ForeignKey(
        Appointment, 
        on_delete=models.CASCADE,
        verbose_name=_("Appointment")
    )
    diagnosis = models.TextField(verbose_name=_("Diagnosis"))
    medicine = models.JSONField(
        default=list,
        verbose_name=_("Medicines")
    )
    advice = models.TextField(
        blank=True,
        verbose_name=_("Medical Advice")
    )
    follow_up_date = models.DateField(
        null=True, 
        blank=True,
        verbose_name=_("Follow-up Date")
    )
    is_digital_signature = models.BooleanField(
        default=False,
        verbose_name=_("Digitally Signed")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    issued_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="issued_prescriptions",
        verbose_name=_("Issued By")
    )

    class Meta:
        verbose_name = _("Prescription")
        verbose_name_plural = _("Prescriptions")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Prescription for {self.appointment.patient.user.username} on {self.created_at.date()}"

    def clean(self):
        """Validate prescription data."""
        super().clean()
        
        # Validate follow-up date is not in the past
        if self.follow_up_date and self.follow_up_date < timezone.now().date():
            raise ValidationError({
                'follow_up_date': _("Follow-up date cannot be in the past.")
            })


class SystemReport(models.Model):
    """Model for system-generated reports."""
    
    class ReportTypeChoices(models.TextChoices):
        USERS = "users", _("User Statistics")
        APPOINTMENTS = "appointments", _("Appointment Reports")
        PRESCRIPTIONS = "prescriptions", _("Prescription Analysis")
        FINANCIAL = "financial", _("Financial Report")
        ACTIVITY = "activity", _("Activity Logs")
        SYSTEM = "system", _("System Performance")

    class FormatChoices(models.TextChoices):
        CSV = "csv", _("CSV")
        PDF = "pdf", _("PDF")
        EXCEL = "excel", _("Excel")
        JSON = "json", _("JSON")

    title = models.CharField(
        max_length=200,
        verbose_name=_("Report Title")
    )
    report_type = models.CharField(
        max_length=50, 
        choices=ReportTypeChoices.choices,
        verbose_name=_("Report Type")
    )
    format = models.CharField(
        max_length=10, 
        choices=FormatChoices.choices, 
        default=FormatChoices.CSV,
        verbose_name=_("Format")
    )
    generated_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        verbose_name=_("Generated By")
    )
    file = models.FileField(
        upload_to="system_reports/%Y/%m/",
        verbose_name=_("Report File")
    )
    generated_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Generated At")
    )
    period_start = models.DateField(verbose_name=_("Period Start"))
    period_end = models.DateField(verbose_name=_("Period End"))
    parameters = models.JSONField(
        default=dict,
        verbose_name=_("Report Parameters")
    )

    class Meta:
        verbose_name = _("System Report")
        verbose_name_plural = _("System Reports")
        ordering = ["-generated_at"]
        indexes = [
            models.Index(fields=['report_type', 'generated_at']),
        ]

    def __str__(self):
        return f"{self.get_report_type_display()} Report ({self.period_start} to {self.period_end})"

    @property
    def is_expired(self):
        """Check if report is older than 30 days."""
        return (timezone.now() - self.generated_at).days > 30


class Announcement(models.Model):
    """Model for system announcements and notifications."""
    
    class PriorityChoices(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    title = models.CharField(
        max_length=200,
        verbose_name=_("Title")
    )
    content = models.TextField(verbose_name=_("Content"))
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        verbose_name=_("Created By")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )
    priority = models.CharField(
        max_length=10, 
        choices=PriorityChoices.choices, 
        default=PriorityChoices.MEDIUM,
        verbose_name=_("Priority")
    )
    target_roles = models.JSONField(
        default=list,
        verbose_name=_("Target Roles")
    )
    start_date = models.DateField(
        default=timezone.now,
        verbose_name=_("Start Date")
    )
    end_date = models.DateField(
        null=True, 
        blank=True,
        verbose_name=_("End Date")
    )
    is_pinned = models.BooleanField(
        default=False,
        verbose_name=_("Pinned Announcement")
    )

    class Meta:
        verbose_name = _("Announcement")
        verbose_name_plural = _("Announcements")
        ordering = ["-is_pinned", "-created_at"]
        indexes = [
            models.Index(fields=['is_active', 'start_date', 'end_date']),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        """Validate announcement dates."""
        super().clean()
        
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({
                'end_date': _("End date cannot be before start date.")
            })
        
        if self.end_date and self.end_date < timezone.now().date():
            raise ValidationError({
                'end_date': _("End date cannot be in the past.")
            })

    @property
    def is_current(self):
        """Check if announcement is currently active."""
        now = timezone.now().date()
        if self.end_date:
            return self.start_date <= now <= self.end_date
        return self.start_date <= now


class ActivityLog(models.Model):
    """Model for tracking system activities and user actions."""
    
    class ActionChoices(models.TextChoices):
        LOGIN = "login", _("User Login")
        LOGOUT = "logout", _("User Logout")
        CREATE = "create", _("Record Created")
        UPDATE = "update", _("Record Updated")
        DELETE = "delete", _("Record Deleted")
        STATUS_CHANGE = "status_change", _("Status Changed")
        PASSWORD_CHANGE = "password_change", _("Password Changed")
        PROFILE_UPDATE = "profile_update", _("Profile Updated")
        APPOINTMENT_BOOKED = "appointment_booked", _("Appointment Booked")
        APPOINTMENT_UPDATED = "appointment_updated", _("Appointment Updated")
        PRESCRIPTION_CREATED = "prescription_created", _("Prescription Created")
        REPORT_GENERATED = "report_generated", _("Report Generated")
        ANNOUNCEMENT_CREATED = "announcement_created", _("Announcement Created")
        BACKUP_CREATED = "backup_created", _("Backup Created")
        MAINTENANCE = "maintenance", _("Maintenance Operation")

    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name=_("User")
    )
    action = models.CharField(
        max_length=50, 
        choices=ActionChoices.choices,
        verbose_name=_("Action")
    )
    model_name = models.CharField(
        max_length=100,
        verbose_name=_("Model Name")
    )
    object_id = models.CharField(
        max_length=100,
        verbose_name=_("Object ID")
    )
    details = models.JSONField(
        default=dict,
        verbose_name=_("Details")
    )
    ip_address = models.GenericIPAddressField(
        null=True, 
        blank=True,
        verbose_name=_("IP Address")
    )
    user_agent = models.TextField(
        blank=True,
        verbose_name=_("User Agent")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )

    class Meta:
        verbose_name = _("Activity Log")
        verbose_name_plural = _("Activity Logs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=['user', 'action']),
            models.Index(fields=['created_at']),
            models.Index(fields=['model_name', 'object_id']),
        ]

    def __str__(self):
        return f"{self.user} {self.get_action_display()} on {self.model_name}"

    @property
    def action_icon(self):
        """Return Bootstrap icon class for the action."""
        icons = {
            'login': 'bi-box-arrow-in-right',
            'logout': 'bi-box-arrow-right',
            'create': 'bi-plus-circle',
            'update': 'bi-pencil',
            'delete': 'bi-trash',
            'status_change': 'bi-toggle-on',
            'password_change': 'bi-key',
            'profile_update': 'bi-person',
            'appointment_booked': 'bi-calendar-plus',
            'appointment_updated': 'bi-calendar-check',
            'prescription_created': 'bi-file-medical',
            'report_generated': 'bi-file-earmark-bar-graph',
            'announcement_created': 'bi-megaphone',
            'backup_created': 'bi-database',
            'maintenance': 'bi-tools',
        }
        return icons.get(self.action, 'bi-activity')

    @property
    def action_color(self):
        """Return Bootstrap color class for the action."""
        colors = {
            'login': 'success',
            'logout': 'secondary',
            'create': 'primary',
            'update': 'info',
            'delete': 'danger',
            'status_change': 'warning',
            'password_change': 'warning',
            'profile_update': 'info',
            'appointment_booked': 'success',
            'appointment_updated': 'info',
            'prescription_created': 'primary',
            'report_generated': 'info',
            'announcement_created': 'primary',
            'backup_created': 'success',
            'maintenance': 'warning',
        }
        return colors.get(self.action, 'secondary')


class SystemSetting(models.Model):
    """Model for storing system configuration settings."""
    
    class SettingTypeChoices(models.TextChoices):
        BOOLEAN = "boolean", _("Boolean")
        STRING = "string", _("String")
        INTEGER = "integer", _("Integer")
        TEXT = "text", _("Text")
        JSON = "json", _("JSON")
        FLOAT = "float", _("Float")

    class CategoryChoices(models.TextChoices):
        GENERAL = "general", _("General")
        SECURITY = "security", _("Security")
        APPOINTMENT = "appointment", _("Appointment")
        NOTIFICATION = "notification", _("Notification")
        BACKUP = "backup", _("Backup")
        MAINTENANCE = "maintenance", _("Maintenance")
        EMAIL = "email", _("Email")
        PAYMENT = "payment", _("Payment")

    key = models.CharField(
        max_length=100, 
        unique=True,
        verbose_name=_("Setting Key")
    )
    value = models.TextField(verbose_name=_("Setting Value"))
    setting_type = models.CharField(
        max_length=10, 
        choices=SettingTypeChoices.choices,
        verbose_name=_("Setting Type")
    )
    category = models.CharField(
        max_length=20, 
        choices=CategoryChoices.choices, 
        default=CategoryChoices.GENERAL,
        verbose_name=_("Category")
    )
    label = models.CharField(
        max_length=200,
        verbose_name=_("Label")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description")
    )
    is_public = models.BooleanField(
        default=False,
        verbose_name=_("Public Setting")
    )
    order = models.IntegerField(
        default=0,
        verbose_name=_("Order")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )
    
    class Meta:
        verbose_name = _("System Setting")
        verbose_name_plural = _("System Settings")
        ordering = ['category', 'order', 'key']
        indexes = [
            models.Index(fields=['category', 'key']),
        ]
    
    def __str__(self):
        return f"{self.key} ({self.category})"
    
    def get_value(self):
        """Return the setting value in the appropriate type."""
        try:
            if self.setting_type == self.SettingTypeChoices.BOOLEAN:
                return self.value.lower() in ('true', '1', 'yes', 'on')
            elif self.setting_type == self.SettingTypeChoices.INTEGER:
                return int(self.value)
            elif self.setting_type == self.SettingTypeChoices.FLOAT:
                return float(self.value)
            elif self.setting_type == self.SettingTypeChoices.JSON:
                return json.loads(self.value)
            else:
                return self.value
        except (ValueError, json.JSONDecodeError):
            # Return default value based on type if parsing fails
            if self.setting_type == self.SettingTypeChoices.BOOLEAN:
                return False
            elif self.setting_type in [self.SettingTypeChoices.INTEGER, self.SettingTypeChoices.FLOAT]:
                return 0
            elif self.setting_type == self.SettingTypeChoices.JSON:
                return {}
            return self.value
    
    def set_value(self, new_value):
        """Set the setting value with proper type conversion."""
        if self.setting_type == self.SettingTypeChoices.BOOLEAN:
            self.value = 'true' if new_value else 'false'
        elif self.setting_type == self.SettingTypeChoices.INTEGER:
            self.value = str(int(new_value))
        elif self.setting_type == self.SettingTypeChoices.FLOAT:
            self.value = str(float(new_value))
        elif self.setting_type == self.SettingTypeChoices.JSON:
            self.value = json.dumps(new_value)
        else:
            self.value = str(new_value)


class BackupLog(models.Model):
    """Model for tracking system backup operations."""
    
    class StatusChoices(models.TextChoices):
        PENDING = "pending", _("Pending")
        RUNNING = "running", _("Running")
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    class BackupTypeChoices(models.TextChoices):
        FULL = "full", _("Full Backup")
        INCREMENTAL = "incremental", _("Incremental Backup")
        DATABASE = "database", _("Database Only")
        MEDIA = "media", _("Media Files Only")
        SYSTEM = "system", _("System Configuration")

    backup_type = models.CharField(
        max_length=20, 
        choices=BackupTypeChoices.choices,
        verbose_name=_("Backup Type")
    )
    filename = models.CharField(
        max_length=255,
        verbose_name=_("Filename")
    )
    file_path = models.FileField(
        upload_to='backups/%Y/%m/%d/',
        null=True, 
        blank=True,
        verbose_name=_("File Path")
    )
    file_size = models.BigIntegerField(
        default=0,
        verbose_name=_("File Size")
    )
    status = models.CharField(
        max_length=10, 
        choices=StatusChoices.choices, 
        default=StatusChoices.PENDING,
        verbose_name=_("Status")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name=_("Created By")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    completed_at = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name=_("Completed At")
    )
    duration = models.DurationField(
        null=True,
        blank=True,
        verbose_name=_("Duration")
    )
    
    class Meta:
        verbose_name = _("Backup Log")
        verbose_name_plural = _("Backup Logs")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_backup_type_display()} - {self.status}"

    @property
    def human_file_size(self):
        """Return human-readable file size."""
        if self.file_size == 0:
            return "0 B"
        
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"


class MaintenanceLog(models.Model):
    """Model for tracking system maintenance operations."""
    
    class MaintenanceTypeChoices(models.TextChoices):
        SYSTEM = "system", _("System Maintenance")
        DATABASE = "database", _("Database Maintenance")
        BACKUP = "backup", _("Backup Operation")
        UPDATE = "update", _("System Update")
        CLEANUP = "cleanup", _("Cleanup Operation")
        SECURITY = "security", _("Security Update")
        PERFORMANCE = "performance", _("Performance Optimization")

    maintenance_type = models.CharField(
        max_length=20, 
        choices=MaintenanceTypeChoices.choices,
        verbose_name=_("Maintenance Type")
    )
    description = models.TextField(verbose_name=_("Description"))
    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Started At")
    )
    completed_at = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name=_("Completed At")
    )
    status = models.CharField(
        max_length=10, 
        choices=BackupLog.StatusChoices, 
        default=BackupLog.StatusChoices.PENDING,
        verbose_name=_("Status")
    )
    affected_records = models.IntegerField(
        default=0,
        verbose_name=_("Affected Records")
    )
    duration = models.DurationField(
        null=True, 
        blank=True,
        verbose_name=_("Duration")
    )
    initiated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name=_("Initiated By")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )
    system_down = models.BooleanField(
        default=False,
        verbose_name=_("System Down")
    )
    down_time = models.DurationField(
        null=True,
        blank=True,
        verbose_name=_("Down Time")
    )
    
    class Meta:
        verbose_name = _("Maintenance Log")
        verbose_name_plural = _("Maintenance Logs")
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['maintenance_type', 'started_at']),
        ]
    
    def __str__(self):
        return f"{self.get_maintenance_type_display()} - {self.status}"

    def save(self, *args, **kwargs):
        """Calculate duration when completed."""
        if self.completed_at and self.started_at and not self.duration:
            self.duration = self.completed_at - self.started_at
        super().save(*args, **kwargs)

    @property
    def is_completed(self):
        """Check if maintenance is completed."""
        return self.status == BackupLog.StatusChoices.SUCCESS and self.completed_at is not None