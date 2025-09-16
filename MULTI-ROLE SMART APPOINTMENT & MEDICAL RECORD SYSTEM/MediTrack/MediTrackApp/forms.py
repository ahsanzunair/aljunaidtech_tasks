from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from phonenumber_field.formfields import PhoneNumberField as PhoneField
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from .models import *


class UserRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=100, required=True)
    last_name = forms.CharField(max_length=100, required=True)
    email = forms.EmailField(required=True)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)
    phone_number = PhoneField(region="PK", max_length=20, required=True)
    gender = forms.ChoiceField(choices=User.GENDER_CHOICES, required=True)
    date_of_birth = forms.DateField(
        required=True, widget=forms.DateInput(attrs={"type": "date"}))
    role = forms.ChoiceField(
        choices=[("doctor", "Doctor"), ("patient", "Patient")], required=True)
    profile_pic = forms.ImageField(required=False)

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "username",
            "email",
            "password1",
            "password2",
            "phone_number",
            "gender",
            "date_of_birth",
            "role",
            "profile_pic",
        ]

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('This email is already in use.')
        return email


class UserLoginForm(AuthenticationForm):
    username = forms.CharField(label="Username")
    password = forms.CharField(widget=forms.PasswordInput())


class AdminUserForm(forms.ModelForm):
    admin_code = forms.CharField(
        max_length=50,
        required=False,
        label="Admin Access Code",
        help_text="Unique identifier for admin users",
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "gender",
            "date_of_birth",
            "role",
            "is_active",
            "admin_code",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, "admin_profile"):
            self.initial["admin_code"] = self.instance.admin_profile.admin_code

    def clean_admin_code(self):
        admin_code = self.cleaned_data.get("admin_code")
        if admin_code:
            if AdminProfile.objects.filter(admin_code=admin_code).exclude(user=self.instance).exists():
                raise ValidationError("This admin code is already in use.")
            if len(admin_code) < 4:
                raise ValidationError(
                    "Admin code must be at least 4 characters long.")
        return admin_code

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("role") == "admin" and not cleaned.get("admin_code"):
            raise ValidationError("Admin code is required for admin users.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=commit)
        if self.cleaned_data.get("role") == "admin":
            profile, _ = AdminProfile.objects.get_or_create(user=user)
            profile.admin_code = self.cleaned_data.get("admin_code")
            profile.save()
        else:
            # If user changed from admin to another role, optionally remove admin profile
            AdminProfile.objects.filter(user=user).delete()
        return user


class PatientProfileForm(forms.ModelForm):
    class Meta:
        model = PatientProfile
        fields = ["blood_group", "allergies",
                  "medical_history", "emergency_contact"]


class DoctorProfileForm(forms.ModelForm):
    available_days = forms.JSONField(
        widget=forms.HiddenInput(), required=False)
    available_time_slots = forms.JSONField(
        widget=forms.HiddenInput(), required=False)

    class Meta:
        model = DoctorProfile
        fields = [
            "specialization",
            "hospital",
            "city",
            "license_number",
            "consultation_fee",
            "available_days",
            "available_time_slots",
        ]


class AppointmentBookingForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and getattr(user, "role", None) == "patient":
            self.fields["doctor"].queryset = DoctorProfile.objects.filter(
                user__is_active=True)
            if hasattr(user, "patient_profile"):
                self.fields["patient"].initial = user.patient_profile
                self.fields["patient"].widget = forms.HiddenInput()

    class Meta:
        model = Appointment
        fields = ["patient", "doctor", "date", "time",
                  "symptoms", "reason", "other_reason"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "time": forms.TimeInput(attrs={"type": "time"}),
            "symptoms": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get("date")
        time = cleaned.get("time")
        doctor = cleaned.get("doctor")
        if date and date < timezone.now().date():
            raise ValidationError(
                "You cannot book an appointment in the past.")
        if doctor and date and time:
            if Appointment.objects.filter(doctor=doctor, date=date, time=time).exists():
                raise ValidationError("This time slot is already booked.")
        return cleaned


class CancelAppointmentForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter the reason for cancellation...'
        }),
        required=True,
        label='Cancellation Reason'
    )

    def clean_reason(self):
        reason = self.cleaned_data.get('reason')
        if len(reason.strip()) < 10:
            raise ValidationError(
                "Please provide a detailed reason (at least 10 characters)")
        return reason


class MedicineForm(forms.Form):
    name = forms.CharField(max_length=100)
    dose = forms.CharField(max_length=50)
    duration = forms.CharField(max_length=50)
    instructions = forms.CharField(max_length=200, required=False)


class PrescriptionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["follow_up_date"].widget = forms.DateInput(
            attrs={"type": "date"})
        self.fields["diagnosis"].widget = forms.Textarea(attrs={"rows": 3})
        self.fields["advice"].widget = forms.Textarea(attrs={"rows": 3})

    class Meta:
        model = Prescription
        fields = ["diagnosis", "medicine", "advice",
                  "follow_up_date", "is_digital_signature"]
        widgets = {"medicine": forms.HiddenInput()}

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("diagnosis"):
            raise ValidationError("Diagnosis is required.")
        return cleaned


class MedicalRecordForm(forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ["file", "record_type", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class AppointmentStatusForm(forms.ModelForm):
    end_time = forms.TimeField(widget=forms.TimeInput(
        attrs={"type": "time"}), required=False)

    class Meta:
        model = Appointment
        fields = ["status", "end_time"]


class DoctorAvailabilityForm(forms.ModelForm):
    class Meta:
        model = DoctorProfile
        fields = ["available_days", "available_time_slots"]


class SystemReportForm(forms.Form):
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

    Report_type = forms.ChoiceField(
        choices=REPORT_TYPES,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.Select(attrs={"class": "form-control", "type": "date"}),
        initial=(timezone.now() - timedelta(days=30)).date()
    )
    
    end_date = forms.DateField(
        required=False,
        widget=forms.Select(attrs={"class": "form-control", "type": "date"}),
        initial=(timezone.now() - timedelta(days=30)).date()
    )
    
    doctor = forms.ModelChoiceField(
        queryset=DoctorProfile.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        report_type = cleaned_data.get("report_type")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        
        
        if report_type == "appointment" and (not start_date or not end_date):
            raise forms.ValidationError("Date range is required for appointment reports")
        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("Start date cannot be after end date")
        return cleaned_data


class AnnouncementForm(forms.ModelForm):
    target_roles = forms.MultipleChoiceField(
        choices=User.ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        initial=['admin', 'doctor', 'patient']
    )

    class Meta:
        model = Announcement
        fields = ['title', 'content', 'priority', 'target_roles', 'start_date', 'end_date', 'is_active']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # Editing existing announcement
            self.fields['target_roles'].initial = self.instance.target_roles
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if end_date and end_date < start_date:
            self.add_error('end_date', "End date cannot be before start date")
        
        return cleaned_data
    
    def save(self, commit=True):
        announcement = super().save(commit=False)
        announcement.created_by = self.request.user
        
        if commit:
            announcement.save()
        
        return announcement


class AppointmentFilterForm(forms.Form):
    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label='From'
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label='To'
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False
    )
    doctor = forms.ModelChoiceField(
        queryset=DoctorProfile.objects.all(),
        required=False
    )
    patient = forms.ModelChoiceField(
        queryset=PatientProfile.objects.all(),
        required=False
    )


class AddUserForm(UserCreationForm):
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Enter first name'})
    )
    last_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Enter last name'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'placeholder': 'Enter email address'})
    )
    phone_number = PhoneNumberField(
        region="PK",
    )
    gender = forms.ChoiceField(
        choices=User.GENDER_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    role = forms.ChoiceField(
        choices=[("doctor", "Doctor"), ("patient",
                                        "Patient"), ("admin", "Admin")],
        widget=forms.Select(
            attrs={'class': 'form-select', 'id': 'role-select'})
    )
    profile_pic = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    admin_code = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter admin code',
            'class': 'form-control',
            'id': 'admin-code'
        })
    )
    specialization = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Cardiology, Neurology etc.',
            'class': 'form-control',
            'id': 'specialization'
        })
    )
    license_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Medical license number',
            'class': 'form-control',
            'id': 'license-number'
        })
    )
    blood_group = forms.CharField(
        max_length=5,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'A+, B-, O+ etc.',
            'class': 'form-control',
            'id': 'blood-group'
        })
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'phone_number', 'gender', 'date_of_birth', 'role',
            'profile_pic', 'password1', 'password2'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update(
            {'placeholder': 'Enter username'})
        self.fields['password1'].widget.attrs.update(
            {'placeholder': 'Create password'})
        self.fields['password2'].widget.attrs.update(
            {'placeholder': 'Confirm password'})

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        admin_code = cleaned_data.get('admin_code')

        if role == 'admin' and not admin_code:
            self.add_error(
                'admin_code', 'Admin code is required for admin users')

        if role == 'doctor' and not cleaned_data.get('specialization'):
            self.add_error('specialization',
                           'Specialization is required for doctors')

        if role == 'doctor' and not cleaned_data.get('license_number'):
            self.add_error('license_number',
                           'License number is required for doctors')

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data.get('role')

        if commit:
            user.save()

            if role == 'doctor':
                DoctorProfile.objects.create(
                    user=user,
                    specialization=self.cleaned_data['specialization'],
                    license_number=self.cleaned_data['license_number']
                )
            elif role == 'patient':
                PatientProfile.objects.create(
                    user=user,
                    blood_group=self.cleaned_data.get('blood_group', '')
                )
            elif role == 'admin':
                AdminProfile.objects.create(
                    user=user,
                    admin_code=self.cleaned_data['admin_code']
                )

        return user


class ActivityLogFilterForm(forms.Form):
    ACTION_CHOICES = [
        ('', 'All Actions'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('status_change', 'Status Change'),
        ('password_change', 'Password Change'),
        ('appointment_booked', 'Appointment Booked'),
        ('prescription_created', 'Prescription Created'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search in details...'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to and date_from > date_to:
            self.add_error('date_to', "End date cannot be before start date")
        
        return cleaned_data



class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ['value']
        widgets = {
            'value': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        setting = self.instance
        
        if setting.setting_type == 'boolean':
            self.fields['value'] = forms.BooleanField(
                required=False,
                widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
                label=setting.label,
                help_text=setting.description
            )
            self.fields['value'].initial = setting.get_value()
        
        elif setting.setting_type == 'integer':
            self.fields['value'] = forms.IntegerField(
                widget=forms.NumberInput(attrs={'class': 'form-control'}),
                label=setting.label,
                help_text=setting.description
            )
        
        elif setting.setting_type == 'text':
            self.fields['value'] = forms.CharField(
                widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
                label=setting.label,
                help_text=setting.description,
                required=False
            )
        
        else:
            self.fields['value'] = forms.CharField(
                widget=forms.TextInput(attrs={'class': 'form-control'}),
                label=setting.label,
                help_text=setting.description,
                required=False
            )

class BackupForm(forms.Form):
    BACKUP_TYPES = [
        ('database', 'Database Only'),
        ('media', 'Media Files Only'),
        ('full', 'Full Backup (Database + Media)'),
    ]
    
    backup_type = forms.ChoiceField(
        choices=BACKUP_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='database'
    )
    include_logs = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Include activity logs in backup"
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional notes about this backup'}),
        max_length=500
    )

class MaintenanceForm(forms.Form):
    MAINTENANCE_TYPES = [
        ('cleanup_logs', 'Cleanup Old Logs'),
        ('optimize_db', 'Optimize Database'),
        ('clear_cache', 'Clear System Cache'),
    ]
    
    maintenance_type = forms.ChoiceField(
        choices=MAINTENANCE_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='cleanup_logs'
    )
    parameters = forms.JSONField(
        required=False,
        widget=forms.HiddenInput(),
        initial={}
    )