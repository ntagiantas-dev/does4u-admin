import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
from datetime import datetime
import streamlit as st


class EmailService:
    """Brevo SMTP Email Service for sending automation reports"""
    
    def __init__(self):
        self.smtp_server = "smtp-relay.brevo.com"
        self.smtp_port = 587
        self.sender_email = st.secrets.get("BREVO_LOGIN", "")
        self.sender_password = st.secrets.get("BREVO_SMTP_API_KEY", "")
        self.recipient_email = "does4u.ceo@gmail.com"
    
    def _create_html_body(self, form_data: dict) -> str:
        """Generate beautiful HTML email body"""
        html = f"""
        <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: #f9f9f9; padding: 20px; border-radius: 8px; }}
                    .header {{ background: linear-gradient(135deg, #3776ab 0%, #1e3a5f 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center; }}
                    .header h1 {{ margin: 0; font-size: 24px; }}
                    .section {{ background: white; padding: 15px; margin-bottom: 15px; border-left: 4px solid #FFD43B; border-radius: 4px; }}
                    .section h3 {{ margin-top: 0; color: #3776ab; font-size: 16px; }}
                    .field {{ margin: 8px 0; }}
                    .field-label {{ font-weight: bold; color: #3776ab; font-size: 12px; text-transform: uppercase; }}
                    .field-value {{ color: #555; margin-top: 3px; word-break: break-word; }}
                    .footer {{ text-align: center; font-size: 12px; color: #999; margin-top: 30px; padding-top: 15px; border-top: 1px solid #ddd; }}
                    .timestamp {{ color: #999; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🤖 Does4U Automation Report</h1>
                        <p style="margin: 5px 0;">New Lead from Pre-Sales Assistant Spyros</p>
                    </div>
                    
                    <div class="section">
                        <h3>📋 Contact Information</h3>
                        <div class="field">
                            <div class="field-label">Name</div>
                            <div class="field-value">{form_data.get('name', 'N/A')}</div>
                        </div>
                        <div class="field">
                            <div class="field-label">Email</div>
                            <div class="field-value">{form_data.get('email', 'N/A')}</div>
                        </div>
                        <div class="field">
                            <div class="field-label">Company</div>
                            <div class="field-value">{form_data.get('company', 'N/A')}</div>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h3>🎯 Problem & Solution</h3>
                        <div class="field">
                            <div class="field-label">Problem Description</div>
                            <div class="field-value">{form_data.get('problem_description', 'N/A')}</div>
                        </div>
                        <div class="field">
                            <div class="field-label">Current Process</div>
                            <div class="field-value">{form_data.get('current_process', 'N/A')}</div>
                        </div>
                        <div class="field">
                            <div class="field-label">Desired Outcome</div>
                            <div class="field-value">{form_data.get('desired_outcome', 'N/A')}</div>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h3>📊 Technical Details</h3>
                        <div class="field">
                            <div class="field-label">Websites Involved</div>
                            <div class="field-value">{', '.join(form_data.get('websites', [])) if form_data.get('websites') else 'N/A'}</div>
                        </div>
                        <div class="field">
                            <div class="field-label">Documents Involved</div>
                            <div class="field-value">{', '.join(form_data.get('documents', [])) if form_data.get('documents') else 'N/A'}</div>
                        </div>
                        <div class="field">
                            <div class="field-label">Estimated Volume</div>
                            <div class="field-value">{form_data.get('estimated_volume', 'N/A')}</div>
                        </div>
                    </div>
                    
                    {f'<div class="section"><h3>📝 Additional Notes</h3><div class="field"><div class="field-value">{form_data.get("additional_notes", "N/A")}</div></div></div>' if form_data.get('additional_notes') else ''}
                    
                    <div class="footer">
                        <p class="timestamp">Submitted on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p>This report was generated by Spyros Pre-Sales AI Assistant</p>
                        <p>© 2026 Does4U Automation Agency</p>
                    </div>
                </div>
            </body>
        </html>
        """
        return html
    
    def send_report(self, form_data: dict) -> tuple[bool, str]:
        """
        Send automation report via email
        
        Args:
            form_data: Dictionary with lead information
        
        Returns:
            (success: bool, message: str)
        """
        try:
            # Validate credentials
            if not self.sender_email or not self.sender_password:
                return False, "❌ Brevo credentials not configured in Streamlit secrets"
            
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = f"🤖 Does4U Automation Report - {form_data.get('name', 'New Lead')}"
            message["From"] = self.sender_email
            message["To"] = self.recipient_email
            
            # Create HTML and plain text versions
            html_body = self._create_html_body(form_data)
            text_body = f"""
Does4U Automation Report
========================

Contact Information:
Name: {form_data.get('name', 'N/A')}
Email: {form_data.get('email', 'N/A')}
Company: {form_data.get('company', 'N/A')}

Problem & Solution:
Problem: {form_data.get('problem_description', 'N/A')}
Current: {form_data.get('current_process', 'N/A')}
Desired: {form_data.get('desired_outcome', 'N/A')}

Technical Details:
Websites: {', '.join(form_data.get('websites', [])) or 'N/A'}
Documents: {', '.join(form_data.get('documents', [])) or 'N/A'}
Volume: {form_data.get('estimated_volume', 'N/A')}

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            # Attach both versions
            message.attach(MIMEText(text_body, "plain"))
            message.attach(MIMEText(html_body, "html"))
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, self.recipient_email, message.as_string())
            
            return True, "✅ Report sent successfully to does4u.ceo@gmail.com"
        
        except smtplib.SMTPAuthenticationError:
            return False, "❌ Brevo authentication failed. Check BREVO_LOGIN and BREVO_SMTP_API_KEY"
        except smtplib.SMTPException as e:
            return False, f"❌ Email error: {str(e)}"
        except Exception as e:
            return False, f"❌ Error: {str(e)}"