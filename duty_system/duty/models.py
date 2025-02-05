from django.db import models
from django.contrib.auth.models import User

class Staff(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # ... 其他字段

class Holiday(models.Model):
    date = models.DateField()
    description = models.CharField(max_length=100)
    # ... 其他字段

class DutySchedule(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    date = models.DateField()
    is_holiday = models.BooleanField(default=False)  # 添加节假日标记
    
    class Meta:
        ordering = ['date']
        unique_together = ['date', 'staff']

    def __str__(self):
        return f"{self.staff.user.username} - {self.date}"

class ShiftChangeRequest(models.Model):
    requester = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='requested_changes')
    date = models.DateField()
    # ... 其他字段

class DutyOrder(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    order = models.IntegerField()  # 排序号
    is_active = models.BooleanField(default=True)  # 是否参与排班
    
    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.staff.user.username} - 顺序{self.order}"

class DutySwapRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('accepted', '已接受'),
        ('rejected', '已拒绝'),
        ('cancelled', '已取消'),
    ]

    requester = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='swap_requests_sent')
    target = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='swap_requests_received')
    requester_duty = models.ForeignKey(DutySchedule, on_delete=models.CASCADE, related_name='swap_requests_as_requester')
    target_duty = models.ForeignKey(DutySchedule, on_delete=models.CASCADE, related_name='swap_requests_as_target')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requester.user.username} 请求与 {self.target.user.username} 换班"

    def accept(self):
        if self.status == 'pending':
            # 交换值班安排
            requester_staff = self.requester_duty.staff
            target_staff = self.target_duty.staff
            
            self.requester_duty.staff = target_staff
            self.target_duty.staff = requester_staff
            
            self.requester_duty.save()
            self.target_duty.save()
            
            self.status = 'accepted'
            self.save()

    def reject(self):
        if self.status == 'pending':
            self.status = 'rejected'
            self.save()

    def cancel(self):
        if self.status == 'pending':
            self.status = 'cancelled'
            self.save()