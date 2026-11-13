"""`{% staff_numbers %}`: the numbers at the top of the Django admin's first page."""

from django import template

from apps.responses.staff_numbers import numbers_for

register = template.Library()


@register.inclusion_tag("admin/_staff_numbers.html", takes_context=True)
def staff_numbers(context):
    return {"lines": numbers_for(context["request"])}
