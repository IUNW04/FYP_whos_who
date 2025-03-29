from django import template

register = template.Library()

@register.filter
def split(value, arg):
    """Split a string into a list on the given delimiter"""
    if value:
        return [x.strip() for x in value.split(arg)]
    return []

@register.filter
def strip(value):
    """Strip whitespace from a string"""
    if value:
        return value.strip()
    return ''

@register.filter
def get_attribute(obj, attr):
    """Gets an attribute of an object dynamically from a string name"""
    try:
        # Python's built-in getattr with default value
        return getattr(obj, attr, '')
    except (AttributeError, TypeError):
        return ''

@register.filter
def has_staff_profile(user):
    """Check if a user has a staff profile"""
    return hasattr(user, 'staffprofile')

@register.filter
def cut(value, arg):
    """Remove all values of arg from the given string"""
    if value:
        return value.replace(arg, '')
    return ''
