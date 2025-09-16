from django.core.management.base import BaseCommand
from MediTrackApp.models import SystemSetting

class Command(BaseCommand):
    help = 'Load initial system settings'
    
    def handle(self, *args, **options):
        settings_data = [
            # General Settings
            {
                'key': 'site_name',
                'value': 'Multi-Role Smart Appointment System',
                'setting_type': 'string',
                'category': 'general',
                'label': 'Site Name',
                'description': 'The name of your application',
                'order': 1
            },
            {
                'key': 'site_description',
                'value': 'Comprehensive medical appointment management system',
                'setting_type': 'text',
                'category': 'general',
                'label': 'Site Description',
                'description': 'Brief description of your application',
                'order': 2
            },
            
            # Security Settings
            {
                'key': 'login_attempts',
                'value': '5',
                'setting_type': 'integer',
                'category': 'security',
                'label': 'Max Login Attempts',
                'description': 'Maximum number of failed login attempts before account lock',
                'order': 1
            },
            {
                'key': 'session_timeout',
                'value': '30',
                'setting_type': 'integer',
                'category': 'security',
                'label': 'Session Timeout (minutes)',
                'description': 'User session timeout in minutes',
                'order': 2
            },
            
            # Appointment Settings
            {
                'key': 'appointment_duration',
                'value': '30',
                'setting_type': 'integer',
                'category': 'appointment',
                'label': 'Default Appointment Duration (minutes)',
                'description': 'Default duration for appointments in minutes',
                'order': 1
            },
            {
                'key': 'max_daily_appointments',
                'value': '20',
                'setting_type': 'integer',
                'category': 'appointment',
                'label': 'Max Daily Appointments per Doctor',
                'description': 'Maximum number of appointments a doctor can have per day',
                'order': 2
            },
        ]
        
        for data in settings_data:
            setting, created = SystemSetting.objects.get_or_create(
                key=data['key'],
                defaults=data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created setting: {data["key"]}'))
            else:
                self.stdout.write(self.style.WARNING(f'Setting already exists: {data["key"]}'))