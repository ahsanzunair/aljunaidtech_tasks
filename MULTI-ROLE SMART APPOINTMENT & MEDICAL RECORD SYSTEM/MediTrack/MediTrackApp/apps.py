from django.apps import AppConfig


class MeditrackappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'MediTrackApp'



class YourAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'MediTrackApp'
    
    def ready(self):
        import MediTrackApp.signals