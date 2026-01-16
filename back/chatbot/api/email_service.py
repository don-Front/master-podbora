# -*- coding: utf-8 -*-
"""
Сервис для работы с email: валидация и отправка уведомлений.
"""

import re
import smtplib
import socket
import dns.resolver
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, Tuple, List

from .email_config import (
    SMTP_CONFIG, 
    EMAIL_CREDENTIALS, 
    NOTIFICATION_RECIPIENTS,
    EMAIL_VALIDATION,
    EMAIL_TEMPLATES
)


class EmailValidator:
    """Класс для валидации email адресов"""
    
    # Регулярное выражение для проверки формата email
    EMAIL_REGEX = re.compile(
        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    )
    
    @classmethod
    def validate_format(cls, email: str) -> Tuple[bool, str]:
        """
        Проверяет формат email адреса.
        Возвращает (is_valid, error_message)
        """
        if not email:
            return False, "Email не указан"
        
        email = email.strip().lower()
        
        if not cls.EMAIL_REGEX.match(email):
            return False, "Неверный формат email адреса"
        
        return True, ""
    
    @classmethod
    def check_mx_record(cls, email: str) -> Tuple[bool, str]:
        """
        Проверяет существование MX записи для домена email.
        Возвращает (is_valid, error_message)
        """
        if not EMAIL_VALIDATION.get("check_mx", True):
            return True, ""
        
        try:
            domain = email.split('@')[1]
            
            # Устанавливаем таймаут
            resolver = dns.resolver.Resolver()
            resolver.timeout = EMAIL_VALIDATION.get("timeout", 10)
            resolver.lifetime = EMAIL_VALIDATION.get("timeout", 10)
            
            # Пробуем получить MX записи
            mx_records = resolver.resolve(domain, 'MX')
            
            if mx_records:
                return True, ""
            else:
                return False, f"Домен {domain} не принимает почту"
                
        except dns.resolver.NXDOMAIN:
            return False, f"Домен не существует"
        except dns.resolver.NoAnswer:
            return False, f"Домен не имеет почтовых серверов"
        except dns.resolver.Timeout:
            # При таймауте считаем email валидным (не блокируем пользователя)
            return True, ""
        except Exception as e:
            # При других ошибках тоже пропускаем
            print(f"[WARNING] MX check error: {e}")
            return True, ""
    
    @classmethod
    def validate_email(cls, email: str) -> Tuple[bool, str]:
        """
        Полная валидация email адреса.
        Возвращает (is_valid, error_message)
        """
        # Проверяем формат
        is_valid, error = cls.validate_format(email)
        if not is_valid:
            return False, error
        
        # Проверяем MX записи
        is_valid, error = cls.check_mx_record(email.strip().lower())
        if not is_valid:
            return False, error
        
        return True, ""


class EmailSender:
    """Класс для отправки email уведомлений"""
    
    @staticmethod
    def _create_smtp_connection():
        """Создает SMTP соединение"""
        try:
            if SMTP_CONFIG.get("use_ssl", False):
                server = smtplib.SMTP_SSL(
                    SMTP_CONFIG["host"],
                    SMTP_CONFIG["port"],
                    timeout=SMTP_CONFIG.get("timeout", 30)
                )
            else:
                server = smtplib.SMTP(
                    SMTP_CONFIG["host"],
                    SMTP_CONFIG["port"],
                    timeout=SMTP_CONFIG.get("timeout", 30)
                )
                
                if SMTP_CONFIG.get("use_tls", True):
                    server.starttls()
            
            # Авторизация
            server.login(
                EMAIL_CREDENTIALS["sender_email"],
                EMAIL_CREDENTIALS["sender_password"]
            )
            
            return server
            
        except Exception as e:
            print(f"[ERROR] SMTP connection failed: {e}")
            raise
    
    @classmethod
    def send_chat_notification(
        cls,
        category: str,
        messages: List[dict],
        client_email: str = "Не указан",
        client_phone: str = "Не указан",
        ip_address: str = "Неизвестен",
        chat_date: datetime = None
    ) -> Tuple[bool, str]:
        """
        Отправляет уведомление о новом обращении в чат-бот.
        
        Args:
            category: Категория обращения (Продажа, Поверка и т.д.)
            messages: Список сообщений диалога
            client_email: Email клиента
            client_phone: Телефон клиента
            ip_address: IP адрес клиента
            chat_date: Дата создания чата
        
        Returns:
            (success, error_message)
        """
        try:
            # Формируем HTML контент сообщений
            messages_html = ""
            for msg in messages:
                sender = "Клиент" if msg.get("is_user", True) else "Бот"
                css_class = "user" if msg.get("is_user", True) else "bot"
                content = msg.get("content", "")
                time_str = ""
                if msg.get("created_at"):
                    try:
                        dt = datetime.fromisoformat(str(msg["created_at"]).replace('Z', '+00:00'))
                        time_str = dt.strftime("%H:%M")
                    except:
                        pass
                
                messages_html += f"""
                <div class="message {css_class}">
                    <div class="label">{sender} {time_str}</div>
                    <div>{content}</div>
                </div>
                """
            
            # Форматируем дату
            date_str = chat_date.strftime("%d.%m.%Y %H:%M") if chat_date else datetime.now().strftime("%d.%m.%Y %H:%M")
            
            # Формируем письмо
            subject = EMAIL_TEMPLATES["subject"].format(category=category)
            html_body = EMAIL_TEMPLATES["html_template"].format(
                category=category,
                client_email=client_email,
                client_phone=client_phone,
                ip_address=ip_address,
                date=date_str,
                messages=messages_html
            )
            
            # Создаем сообщение
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{EMAIL_CREDENTIALS['sender_name']} <{EMAIL_CREDENTIALS['sender_email']}>"
            msg['To'] = NOTIFICATION_RECIPIENTS["main_recipient"]
            
            # Добавляем CC если есть
            cc_recipients = NOTIFICATION_RECIPIENTS.get("cc_recipients", [])
            if cc_recipients:
                msg['Cc'] = ", ".join(cc_recipients)
            
            # Прикрепляем HTML
            html_part = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(html_part)
            
            # Отправляем
            with cls._create_smtp_connection() as server:
                all_recipients = [NOTIFICATION_RECIPIENTS["main_recipient"]] + cc_recipients
                server.sendmail(
                    EMAIL_CREDENTIALS["sender_email"],
                    all_recipients,
                    msg.as_string()
                )
            
            print(f"[INFO] Email notification sent for category: {category}")
            return True, ""
            
        except smtplib.SMTPAuthenticationError:
            error = "Ошибка авторизации SMTP. Проверьте email и пароль в настройках."
            print(f"[ERROR] {error}")
            return False, error
            
        except smtplib.SMTPException as e:
            error = f"Ошибка отправки email: {str(e)}"
            print(f"[ERROR] {error}")
            return False, error
            
        except Exception as e:
            error = f"Неизвестная ошибка при отправке email: {str(e)}"
            print(f"[ERROR] {error}")
            return False, error


def extract_contact_info(text: str) -> Tuple[str, str]:
    """
    Извлекает email и телефон из текста сообщения.
    
    Returns:
        (email, phone)
    """
    email = "Не указан"
    phone = "Не указан"
    
    # Ищем email
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    if email_match:
        email = email_match.group()
    
    # Ищем телефон (различные форматы)
    phone_patterns = [
        r'\+7\s*\(?[0-9]{3}\)?\s*[0-9]{3}[\s-]?[0-9]{2}[\s-]?[0-9]{2}',  # +7 (XXX) XXX-XX-XX
        r'8\s*\(?[0-9]{3}\)?\s*[0-9]{3}[\s-]?[0-9]{2}[\s-]?[0-9]{2}',     # 8 (XXX) XXX-XX-XX
        r'\+7[0-9]{10}',  # +7XXXXXXXXXX
        r'8[0-9]{10}',    # 8XXXXXXXXXX
    ]
    
    for pattern in phone_patterns:
        phone_match = re.search(pattern, text)
        if phone_match:
            phone = phone_match.group()
            break
    
    return email, phone

