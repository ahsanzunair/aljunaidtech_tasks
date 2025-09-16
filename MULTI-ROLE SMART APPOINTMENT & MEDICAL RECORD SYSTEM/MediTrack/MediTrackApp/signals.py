from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.auth.models import User
from .models import *

def create_user_profile(sender, instance, created, **kwargs):
    if created:
        if instance.role == "doctor":
            DoctorProfile.objects.create(user=instance)
        elif instance.role == "patient":
            PatientProfile.objects.create(user=instance)
        elif instance.role == "admin":
            AdminProfile.objects.create(user=instance)
            


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    ActivityLog.objects.create(
        user=user,
        action='login',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        details={'username': user.username}
    )

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    ActivityLog.objects.create(
        user=user,
        action='logout',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        details={'username': user.username}
    )

@receiver(post_save, sender=User)
def log_user_activity(sender, instance, created, **kwargs):
    if created:
        action = 'create'
        details = {'username': instance.username, 'role': instance.role}
    else:
        action = 'update'
        details = {'username': instance.username, 'changes': get_model_changes(instance)}
    
    ActivityLog.objects.create(
        user=instance,
        action=action,
        model_name='User',
        object_id=instance.id,
        details=details
    )

@receiver(post_save, sender=Appointment)
def log_appointment_activity(sender, instance, created, **kwargs):
    if created:
        action = 'appointment_booked'
    else:
        action = 'appointment_updated'
    
    ActivityLog.objects.create(
        user=instance.patient.user,
        action=action,
        model_name='Appointment',
        object_id=instance.id,
        details={
            'appointment_id': instance.id,
            'patient': instance.patient.user.username,
            'doctor': instance.doctor.user.username,
            'status': instance.status,
            'date': instance.date.isoformat()
        }
    )

@receiver(post_save, sender=Prescription)
def log_prescription_activity(sender, instance, created, **kwargs):
    if created:
        ActivityLog.objects.create(
            user=instance.appointment.doctor.user,
            action='prescription_created',
            model_name='Prescription',
            object_id=instance.id,
            details={
                'prescription_id': instance.id,
                'patient': instance.appointment.patient.user.username,
                'doctor': instance.appointment.doctor.user.username
            }
        )

@receiver(post_save, sender=Announcement)
def log_announcement_activity(sender, instance, created, **kwargs):
    if created:
        ActivityLog.objects.create(
            user=instance.created_by,
            action='announcement_created',
            model_name='Announcement',
            object_id=instance.id,
            details={
                'title': instance.title,
                'priority': instance.priority,
                'target_roles': instance.target_roles
            }
        )

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def get_model_changes(instance):
    return {'model': instance.__class__.__name__, 'id': instance.id}