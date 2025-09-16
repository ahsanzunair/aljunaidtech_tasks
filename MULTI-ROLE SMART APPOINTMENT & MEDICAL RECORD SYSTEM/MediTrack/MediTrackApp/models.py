import os
import json
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from phonenumber_field.modelfields import PhoneNumberField
from django.core.exceptions import ValidationError
from django.utils import timezone



def validate_file_extension(value):
    ext = os.path.splitext(value.name)[1]  # Get the file extension
    valid_extensions = ['.jpg', '.jpeg', '.png']
    if not ext.lower() in valid_extensions:
        raise ValidationError('Unsupported file extension. Only JPG, JPEG, PNG allowed.')


class User(AbstractUser):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("patient", "Patient"),
        ("doctor", "Doctor"),
    ]

    GENDER_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
    ]

    phone_number = PhoneNumberField(region="PK", blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    profile_pic = models.ImageField(upload_to="profile_pics/", validators=[validate_file_extension], blank=True, null=True)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default="patient")
    is_active = models.BooleanField(default=True)
    
    def clean(self):
        # Validate date of birth is not in future
        if self.date_of_birth and self.date_of_birth > timezone.now().date():
            raise ValidationError("Date of birth cannot be in the future")
        
        # Validate admin role requires admin code
        if self.role == "admin" and not hasattr(self, 'admin_profile'):
            raise ValidationError("Admin users must have an admin code")
    
    def save(self, *args, **kwargs):
        self.full_clean()  # Run model validation before saving
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.role})"


class AdminProfile(models.Model):
    user = models.OneToOneField(User, related_name="admin_profile", on_delete=models.CASCADE)
    admin_code = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return f"Admin: {self.user.username}"


class DoctorProfile(models.Model):
    user = models.OneToOneField(User, related_name="doctor_profile", on_delete=models.CASCADE)
    specialization = models.CharField(max_length=100, blank=True)
    qualifications = models.TextField(blank=True)
    hospital = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    license_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    consultation_fee = models.PositiveIntegerField(default=2000)
    available_days = models.JSONField(default=list, blank=True)
    available_time_slots = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["specialization"]),
            models.Index(fields=["city"]),
        ]

    def __str__(self):
        full_name = self.user.get_full_name() or self.user.username
        return f"DR. {full_name} ({self.specialization or 'General'})"


class PatientProfile(models.Model):
    user = models.OneToOneField(User, related_name="patient_profile", on_delete=models.CASCADE)
    blood_group = models.CharField(max_length=5, blank=True)
    allergies = models.TextField(blank=True)
    medical_history = models.TextField(blank=True)
    emergency_contact = PhoneNumberField(region="PK", blank=True)

    def __str__(self):
        return f"Patient: {self.user.get_full_name() or self.user.username}"


class MedicalRecord(models.Model):
    patient = models.ForeignKey(PatientProfile, related_name="medical_records", on_delete=models.CASCADE)
    file = models.FileField(
        upload_to="medical_records/%Y/%m/%d",
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png"])],
    )
    record_type = models.CharField(max_length=50, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Medical Record: {self.id} for {self.patient.user.username}"


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
        ("completed", "Completed"),
    ]

    REASON_CHOICES = [
        ("CHECKUP", "Routine Checkup"),
        ("CONSULT", "General Consultation"),
        ("FEVER", "Fever/Infection"),
        ("INJURY", "Injury Treatment"),
    ]
    

    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE)
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.CASCADE)
    date = models.DateField()
    time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    symptoms = models.TextField(blank=True)
    reason = models.CharField(max_length=50, choices=REASON_CHOICES, default="CONSULT")
    other_reason = models.CharField(max_length=100, blank=True)
    cancellation_reason = models.TextField(blank=True, null=True)
    cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_appointments')
    end_time = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["doctor", "date", "time"], name="unique_doctor_slot"),
        ]
        ordering = ["-date", "time"]

    def __str__(self):
        return f"Appointment: {self.patient.user.username} with DR. {self.doctor.user.username}"


class Prescription(models.Model):
    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE)
    diagnosis = models.TextField()
    medicine = models.JSONField(default=list)
    advice = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True, help_text="Suggested next visit")
    is_digital_signature = models.BooleanField(default=False, help_text="True if doctor digitally signed this prescription")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prescription for {self.appointment.patient.user.username}"


class SystemReport(models.Model):
    REPORT_TYPES = [
        ("users", "User Statistics"),
        ("appointments", "Appointment Reports"),
        ("prescriptions", "Prescription Analysis"),
        ('financial', 'Financial Report'),
    ]
    
    FORMAT_CHOICES = [
        ('csv', 'CSV'),
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
    ]
    

    title = models.CharField(max_length=200, blank=True, null=True)
    report_type = models.CharField(max_length=50, choices=REPORT_TYPES)
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default="csv")
    generated_by = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to="system_reports")
    generated_at = models.DateTimeField(auto_now_add=True)
    period_start = models.DateField()
    period_end = models.DateField()

    def __str__(self):
        return f"{self.get_report_type_display()} Report ({self.period_start} to {self.period_end})"



class Announcement(models.Model):
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    target_roles = models.JSONField(default=list) 
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.title

class ActivityLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'User Login'),
        ('logout', 'User Logout'),
        ('create', 'Record Created'),
        ('update', 'Record Updated'),
        ('delete', 'Record Deleted'),
        ('status_change', 'Status Changed'),
        ('password_change', 'Password Changed'),
        ('profile_update', 'Profile Updated'),
        ('appointment_booked', 'Appointment Booked'),
        ('appointment_updated', 'Appointment Updated'),
        ('prescription_created', 'Prescription Created'),
        ('report_generated', 'Report Generated'),
        ('announcement_created', 'Announcement Created'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} {self.get_action_display()} on {self.model_name}"
    
    @property
    def action_icon(self):
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
        }
        return icons.get(self.action, 'bi-activity')
    
    @property
    def action_color(self):
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
        }
        return colors.get(self.action, 'secondary')



class SystemSetting(models.Model):
    SETTING_TYPES = [
        ('boolean', 'Boolean'),
        ('string', 'String'),
        ('integer', 'Integer'),
        ('text', 'Text'),
        ('json', 'JSON'),
    ]
    
    CATEGORIES = [
        ('general', 'General'),
        ('security', 'Security'),
        ('appointment', 'Appointment'),
        ('notification', 'Notification'),
        ('backup', 'Backup'),
        ('maintenance', 'Maintenance'),
    ]
    
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    setting_type = models.CharField(max_length=10, choices=SETTING_TYPES)
    category = models.CharField(max_length=20, choices=CATEGORIES, default='general')
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['category', 'order', 'key']
    
    def __str__(self):
        return f"{self.key} ({self.category})"
    
    def get_value(self):
        if self.setting_type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes')
        elif self.setting_type == 'integer':
            try:
                return int(self.value)
            except ValueError:
                return 0
        elif self.setting_type == 'json':
            try:
                return json.loads(self.value)
            except json.JSONDecodeError:
                return {}
        else:
            return self.value
    
    def set_value(self, new_value):
        if self.setting_type == 'boolean':
            self.value = 'true' if new_value else 'false'
        elif self.setting_type == 'integer':
            self.value = str(int(new_value))
        elif self.setting_type == 'json':
            self.value = json.dumps(new_value)
        else:
            self.value = str(new_value)

class BackupLog(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('running', 'Running'),
    ]
    
    backup_type = models.CharField(max_length=50)
    filename = models.CharField(max_length=255)
    file_path = models.FileField(upload_to='backups/', null=True, blank=True)
    file_size = models.BigIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.backup_type} - {self.status}"

class MaintenanceLog(models.Model):
    MAINTENANCE_TYPES = [
        ('system', 'System Maintenance'),
        ('database', 'Database Maintenance'),
        ('backup', 'Backup Operation'),
        ('update', 'System Update'),
        ('cleanup', 'Cleanup Operation'),
    ]
    
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPES)
    description = models.TextField()
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=BackupLog.STATUS_CHOICES, default='pending')
    affected_records = models.IntegerField(default=0)
    duration = models.DurationField(null=True, blank=True)
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.get_maintenance_type_display()} - {self.status}"