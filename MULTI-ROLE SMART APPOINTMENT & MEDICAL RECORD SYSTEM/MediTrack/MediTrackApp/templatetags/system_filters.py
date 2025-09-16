from django import template

register = template.Library()

@register.filter
def get_status_class(status):
    status_classes = {
        'healthy': 'success',
        'warning': 'warning',
        'error': 'danger'
    }
    return status_classes.get(status, 'secondary')