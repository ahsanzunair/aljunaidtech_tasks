import csv
import io
from datetime import datetime, timedelta
from django.http import HttpResponse
from django.db.models import Count, Q
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER
from .models import User, Appointment, Prescription

class ReportGenerator:
    @staticmethod
    def generate_user_report(format='csv'):
        users = User.objects.all().order_by('-date_joined')
        
        if format == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="users_report.csv"'
            
            writer = csv.writer(response)
            writer.writerow(['ID', 'Username', 'Full Name', 'Email', 'Phone', 'Role', 'Status', 'Join Date'])
            
            for user in users:
                writer.writerow([
                    user.id,
                    user.username,
                    user.get_full_name(),
                    user.email,
                    user.phone_number or '',
                    user.get_role_display(),
                    'Active' if user.is_active else 'Inactive',
                    user.date_joined.strftime('%Y-%m-%d')
                ])
            return response
        
        elif format == 'pdf':
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="users_report.pdf"'
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            
            elements = []
            
            # Title
            title_style = styles['Title']
            title_style.alignment = TA_CENTER
            elements.append(Paragraph("User Report", title_style))
            elements.append(Spacer(1, 12))
            
            # Content
            for user in users:
                user_text = f"""
                <b>{user.get_full_name()}</b> ({user.username})<br/>
                Email: {user.email} | Phone: {user.phone_number or 'N/A'}<br/>
                Role: {user.get_role_display()} | Status: {'Active' if user.is_active else 'Inactive'}<br/>
                Joined: {user.date_joined.strftime('%Y-%m-%d')}
                """
                elements.append(Paragraph(user_text, styles['Normal']))
                elements.append(Spacer(1, 12))
            
            doc.build(elements)
            pdf = buffer.getvalue()
            buffer.close()
            response.write(pdf)
            return response

    @staticmethod
    def generate_appointment_report(start_date, end_date, format='csv'):
        appointments = Appointment.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        ).order_by('-date', '-time')
        
        if format == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="appointments_{start_date}_to_{end_date}.csv"'
            
            writer = csv.writer(response)
            writer.writerow(['ID', 'Patient', 'Doctor', 'Date', 'Time', 'Status', 'Reason', 'Created At'])
            
            for appt in appointments:
                writer.writerow([
                    appt.id,
                    appt.patient.user.get_full_name(),
                    appt.doctor.user.get_full_name(),
                    appt.date.strftime('%Y-%m-%d'),
                    appt.time.strftime('%H:%M'),
                    appt.get_status_display(),
                    appt.get_reason_display(),
                    appt.created_at.strftime('%Y-%m-%d %H:%M')
                ])
            return response
        
        
    @staticmethod
    def generate_prescription_report(doctor_id=None, format='csv'):
        prescriptions = Prescription.objects.all()
        if doctor_id:
            prescriptions = prescriptions.filter(appointment__doctor_id=doctor_id)
        
        prescriptions = prescriptions.order_by('-created_at')
        
        if format == 'csv':
            response = HttpResponse(content_type='text/csv')
            filename = "prescriptions.csv" if not doctor_id else f"prescriptions_doctor_{doctor_id}.csv"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            writer = csv.writer(response)
            writer.writerow(['ID', 'Patient', 'Doctor', 'Diagnosis', 'Medicines', 'Date'])
            
            for pres in prescriptions:
                writer.writerow([
                    pres.id,
                    pres.appointment.patient.user.get_full_name(),
                    pres.appointment.doctor.user.get_full_name(),
                    pres.diagnosis,
                    ', '.join([med['name'] for med in pres.medicine]),
                    pres.created_at.strftime('%Y-%m-%d')
                ])
            return response