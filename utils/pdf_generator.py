from reportlab.lib.pagesizes import A4, letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime
import os
from flask import current_app
import logging

logger = logging.getLogger(__name__)

class PDFGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._register_fonts()
        
    def _register_fonts(self):
        """Register Vietnamese fonts if available"""
        try:
            # Try to register Arial Unicode MS for Vietnamese characters
            font_path = os.path.join(current_app.root_path, 'static', 'fonts', 'Arial.ttf')
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('Arial', font_path))
            else:
                # Fallback to default fonts
                pdfmetrics.registerFont(TTFont('Helvetica', 'Helvetica'))
        except Exception as e:
            logger.warning(f'Could not register custom fonts: {e}')

    def generate_transcript(self, student, scores, output_path=None):
        """Generate student transcript PDF"""
        if not output_path:
            output_path = f'transcript_{student.student_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        elements = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=TA_CENTER
        )
        elements.append(Paragraph("BẢNG ĐIỂM HỌC TẬP", title_style))
        
        # Student Information
        student_info = [
            ["Mã sinh viên:", student.student_id],
            ["Họ và tên:", student.user.full_name],
            ["Lớp:", student.class_.class_name if student.class_ else "N/A"],
            ["Khóa:", student.course],
            ["Ngày in:", datetime.now().strftime("%d/%m/%Y %H:%M")]
        ]
        
        student_table = Table(student_info, colWidths=[2*inch, 4*inch])
        student_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(student_table)
        elements.append(Spacer(1, 20))
        
        # Academic Summary
        summary_data = [
            ["Tổng số tín chỉ:", str(student.completed_credits)],
            ["GPA tích lũy:", f"{student.gpa:.2f}"],
            ["Xếp loại:", self._get_academic_rank(student.gpa)]
        ]
        
        summary_table = Table([summary_data])
        summary_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))
        
        # Scores Table
        scores_data = [["Mã MH", "Tên môn học", "Số TC", "Điểm QT", "Điểm thi", "Điểm TK", "Điểm chữ", "Kết quả"]]
        
        for score in scores:
            scores_data.append([
                score.course.subject.subject_code,
                score.course.subject.subject_name,
                str(score.course.subject.credits),
                f"{score.process_score:.1f}" if score.process_score else "",
                f"{score.exam_score:.1f}" if score.exam_score else "",
                f"{score.final_score:.1f}" if score.final_score else "",
                score.grade or "",
                "Đạt" if score.final_score and score.final_score >= 5.0 else "Trượt"
            ])
        
        scores_table = Table(scores_data, colWidths=[0.6*inch, 2.5*inch, 0.5*inch, 0.6*inch, 0.6*inch, 0.6*inch, 0.6*inch, 0.6*inch])
        scores_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 8),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.whitesmoke])
        ]))
        elements.append(scores_table)
        
        # Footer
        elements.append(Spacer(1, 30))
        footer_style = ParagraphStyle(
            'Footer',
            parent=self.styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=colors.grey
        )
        elements.append(Paragraph("Bảng điểm được tạo tự động từ Hệ thống Quản lý Sinh viên", footer_style))
        elements.append(Paragraph(f"Thời điểm tạo: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", footer_style))
        
        try:
            doc.build(elements)
            return output_path
        except Exception as e:
            logger.error(f"Error generating transcript PDF: {e}")
            raise

    def generate_class_scores_report(self, class_, scores, output_path=None):
        """Generate class scores report PDF"""
        if not output_path:
            output_path = f'class_scores_{class_.class_code}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        elements = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=14,
            spaceAfter=20,
            alignment=TA_CENTER
        )
        elements.append(Paragraph(f"BÁO CÁO ĐIỂM LỚP {class_.class_name}", title_style))
        
        # Class Information
        class_info = [
            ["Mã lớp:", class_.class_code],
            ["Tên lớp:", class_.class_name],
            ["Khóa:", class_.course],
            ["Giáo viên chủ nhiệm:", class_.teacher.user.full_name if class_.teacher else "N/A"],
            ["Số sinh viên:", str(class_.current_students)],
            ["Ngày in:", datetime.now().strftime("%d/%m/%Y")]
        ]
        
        class_table = Table(class_info, colWidths=[1.5*inch, 4*inch])
        class_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(class_table)
        elements.append(Spacer(1, 20))
        
        # Scores Table
        scores_data = [["STT", "Mã SV", "Họ tên", "Điểm QT", "Điểm thi", "Điểm TK", "Điểm chữ", "Kết quả"]]
        
        for i, score in enumerate(scores, 1):
            scores_data.append([
                str(i),
                score.student.student_id,
                score.student.user.full_name,
                f"{score.process_score:.1f}" if score.process_score else "",
                f"{score.exam_score:.1f}" if score.exam_score else "",
                f"{score.final_score:.1f}" if score.final_score else "",
                score.grade or "",
                "Đạt" if score.final_score and score.final_score >= 5.0 else "Trượt"
            ])
        
        scores_table = Table(scores_data, colWidths=[0.4*inch, 0.8*inch, 2*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch])
        scores_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 8),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.whitesmoke])
        ]))
        elements.append(scores_table)
        
        # Statistics
        elements.append(Spacer(1, 20))
        passed_count = len([s for s in scores if s.final_score and s.final_score >= 5.0])
        pass_rate = (passed_count / len(scores)) * 100 if scores else 0
        
        stats_data = [
            ["Tổng số sinh viên:", str(len(scores))],
            ["Số sinh viên đạt:", str(passed_count)],
            ["Tỷ lệ đạt:", f"{pass_rate:.1f}%"],
            ["Điểm trung bình:", f"{sum(s.final_score for s in scores if s.final_score) / len([s for s in scores if s.final_score]):.2f}" if scores else "N/A"]
        ]
        
        stats_table = Table([stats_data])
        stats_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(stats_table)
        
        try:
            doc.build(elements)
            return output_path
        except Exception as e:
            logger.error(f"Error generating class scores PDF: {e}")
            raise

    def generate_teaching_report(self, teacher, courses, period, output_path=None):
        """Generate teaching report for teacher"""
        if not output_path:
            output_path = f'teaching_report_{teacher.teacher_code}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        elements = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=14,
            spaceAfter=20,
            alignment=TA_CENTER
        )
        elements.append(Paragraph(f"BÁO CÁO GIẢNG DẠY", title_style))
        
        # Teacher Information
        teacher_info = [
            ["Mã giáo viên:", teacher.teacher_code],
            ["Họ và tên:", teacher.user.full_name],
            ["Bộ môn:", teacher.department],
            ["Chức vụ:", teacher.position or "N/A"],
            ["Thời kỳ:", period],
            ["Ngày in:", datetime.now().strftime("%d/%m/%Y")]
        ]
        
        teacher_table = Table(teacher_info, colWidths=[1.5*inch, 4*inch])
        teacher_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(teacher_table)
        elements.append(Spacer(1, 20))
        
        # Courses Table
        courses_data = [["Mã HP", "Tên học phần", "Số TC", "Số SV", "Lịch học", "Phòng", "Trạng thái"]]
        
        total_credits = 0
        total_students = 0
        
        for course in courses:
            courses_data.append([
                course.course_code,
                course.subject.subject_name,
                str(course.subject.credits),
                str(course.current_students),
                course.schedule or "N/A",
                course.room or "N/A",
                course.status
            ])
            total_credits += course.subject.credits
            total_students += course.current_students
        
        courses_table = Table(courses_data, colWidths=[1*inch, 2.5*inch, 0.6*inch, 0.6*inch, 1.5*inch, 0.8*inch, 1*inch])
        courses_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 8),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.whitesmoke])
        ]))
        elements.append(courses_table)
        
        # Summary
        elements.append(Spacer(1, 20))
        summary_data = [
            ["Tổng số học phần:", str(len(courses))],
            ["Tổng số tín chỉ:", str(total_credits)],
            ["Tổng số sinh viên:", str(total_students)],
            ["Số giờ giảng dạy:", str(total_credits * 15)]  # Assuming 15 hours per credit
        ]
        
        summary_table = Table([summary_data])
        summary_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(summary_table)
        
        try:
            doc.build(elements)
            return output_path
        except Exception as e:
            logger.error(f"Error generating teaching report PDF: {e}")
            raise

    def _get_academic_rank(self, gpa):
        """Get academic rank based on GPA"""
        if gpa >= 3.6:
            return "Xuất sắc"
        elif gpa >= 3.2:
            return "Giỏi"
        elif gpa >= 2.5:
            return "Khá"
        elif gpa >= 2.0:
            return "Trung bình"
        else:
            return "Yếu"

# Utility function for easy access
def generate_pdf_report(report_type, data, output_path=None):
    """Utility function to generate different types of PDF reports"""
    generator = PDFGenerator()
    
    if report_type == 'transcript':
        return generator.generate_transcript(data['student'], data['scores'], output_path)
    elif report_type == 'class_scores':
        return generator.generate_class_scores_report(data['class'], data['scores'], output_path)
    elif report_type == 'teaching_report':
        return generator.generate_teaching_report(data['teacher'], data['courses'], data['period'], output_path)
    else:
        raise ValueError(f"Unsupported report type: {report_type}")