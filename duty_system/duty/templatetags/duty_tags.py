from django import template
from datetime import date, datetime

register = template.Library()

@register.filter
def is_user_duty(duty_info, user):
    """检查是否是用户的值班日"""
    return duty_info[0] == user.username if duty_info else False

@register.filter
def format_date(year, month, day):
    """格式化日期为 YYYY-MM-DD 格式"""
    try:
        return f"{year}-{month:02d}-{int(day):02d}"
    except (ValueError, TypeError):
        return ""

@register.filter
def is_future_or_today(date_str):
    """检查日期是否是今天或将来"""
    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        return check_date >= date.today()
    except (ValueError, TypeError):
        return False

@register.filter
def get_item(dictionary, key):
    """获取字典中的值"""
    return dictionary.get(key)

@register.filter
def is_holiday(schedule_info):
    """检查是否是节假日"""
    return schedule_info[1] if schedule_info else False

@register.filter
def get_username(schedule_info):
    """获取用户名"""
    return schedule_info[0] if schedule_info else ''