from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import *

# Inline profiles for User
class AdminProfileInline(admin.StackedInline):
    model = AdminProfile
    can_delete = False
    verbose_name_plural = 'Admin Profile'
    fk_name = 'user'


class DoctorProfileInline(admin.StackedInline):
    model = DoctorProfile
    can_delete = False
    verbose_name_plural = 'Doctor Profile'
    fk_name = 'user'


class PatientProfileInline(admin.StackedInline):
    model = PatientProfile
    can_delete = False
    verbose_name_plural = 'Patient Profile'
    fk_name = 'user'


# Custom User Admin
class UserAdmin(BaseUserAdmin):
    model = User
    list_display = ['username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'is_staff']
    list_filter = ['is_active', 'role', 'gender']
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {
            'fields': (
                'first_name', 'last_name', 'email', 'phone_number',
                'gender', 'date_of_birth', 'profile_pic'
            )
        }),
        ('Role & Permissions', {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role')}
         ),
    )
    search_fields = ['email', 'username', 'first_name', 'last_name']
    ordering = ['username']
    inlines = []

    def get_inlines(self, request, obj):
        if not obj:
            return []
        inlines = []
        if obj.role == 'admin':
            inlines.append(AdminProfileInline)
        elif obj.role == 'doctor':
            inlines.append(DoctorProfileInline)
        elif obj.role == 'patient':
            inlines.append(PatientProfileInline)
        return inlines

# -------- Appointment Admin --------

# @admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'patient_name', 'doctor_name', "date", 'time', 'status', 'reason']
    list_filter = ['status', 'date', 'reason']
    search_fields = ['patient__user__username', 'doctor__user__username']
    ordering = ['-date', 'time']
    def patient_name(self, obj):
        return obj.patient.user.get_full_name() or obj.patient.user.username
    patient_name.short_description = 'Patient'
    
    def doctor_name(self, obj):
        return f'Dr. {obj.doctor.user.get_full_name()}'
    doctor_name.short_description = 'Doctor' 


# -------- Prescription Admin --------

class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ['id', 'appointment', 'diagnosis', 'created_at', 'is_digital_signature']
    list_filter = ['is_digital_signature', 'created_at']
    search_fields = ['appointment__patient__user__username', 'diagnosis']
    ordering = ['-created_at']
    
    
@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_by', 'created_at', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['title', 'content']
    ordering = ['-created_at']


# -------- Activity Log Admin --------
@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'model_name', 'object_id', 'ip_address', 'created_at']
    list_filter = ['action', 'model_name', 'created_at']
    search_fields = ['user__username', 'model_name', 'details']
    ordering = ['-created_at']


# Register all models
admin.site.register(User, UserAdmin)
admin.site.register(AdminProfile)
admin.site.register(DoctorProfile)
admin.site.register(PatientProfile)
admin.site.register(Appointment, AppointmentAdmin)
admin.site.register(Prescription, PrescriptionAdmin)
admin.site.register(MedicalRecord)
admin.site.register(SystemReport)
