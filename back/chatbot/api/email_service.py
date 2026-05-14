# -*- coding: utf-8 -*-
"""
Сервис для работы с email: валидация и отправка уведомлений.
"""

import re
import os
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
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
    # Российский номер: 7 + код (3–9) + 9 цифр
    RU_PHONE_DIGITS = re.compile(r'^7[3-9]\d{9}$')
    
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
            import dns.resolver
        except ImportError:
            print("[WARNING] Установите dnspython: pip install dnspython — MX-проверка email отключена.")
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

    @classmethod
    def validate_phone_ru(cls, raw: str) -> Tuple[bool, str, str]:
        """
        Проверка российского номера. Возвращает (успех, сообщение_об_ошибке, нормализованный_вид).
        """
        if raw is None or not str(raw).strip():
            return False, "Укажите номер телефона.", ""
        digits = re.sub(r'\D', '', str(raw))
        if digits.startswith('8') and len(digits) == 11:
            digits = '7' + digits[1:]
        if len(digits) == 10:
            digits = '7' + digits
        if len(digits) != 11 or not digits.startswith('7'):
            return (
                False,
                "Неверный формат. Укажите российский номер: например +7 903 123-45-67 или 89031234567.",
                "",
            )
        if not cls.RU_PHONE_DIGITS.match(digits):
            return False, "Номер не похож на корректный российский телефон. Проверьте код и количество цифр.", ""
        pretty = f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
        return True, "", pretty

    @classmethod
    def validate_email_format_or_phone_ru(cls, raw: str) -> Tuple[bool, str, str, str]:
        """
        Поле «почта или телефон»: допускается либо формат email (без MX-проверки),
        либо российский номер. Возвращает (ok, error, kind, normalized),
        kind — 'email' | 'phone' | ''.
        """
        text = (raw or "").strip()
        if not text:
            return False, "Укажите адрес электронной почты или номер телефона.", "", ""
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 10:
            pok, perr, pretty = cls.validate_phone_ru(text)
            if pok:
                return True, "", "phone", pretty
            if "@" not in text:
                return False, perr, "", ""
        ok_fmt, err_fmt = cls.validate_format(text)
        if ok_fmt:
            return True, "", "email", text.strip().lower()
        if "@" in text:
            return False, err_fmt, "", ""
        pok2, perr2, pretty2 = cls.validate_phone_ru(text)
        if pok2:
            return True, "", "phone", pretty2
        return (
            False,
            "Укажите корректный email или российский номер (например +7 903 123-45-67).",
            "",
            "",
        )


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
        chat_date: datetime = None,
        image_paths: List[str] = None
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
            image_paths: Список путей к изображениям для прикрепления
        
        Returns:
            (success, error_message)
        """
        try:
            image_paths = image_paths or []
            image_cid_map = {}  # Маппинг путей к CID для inline изображений
            
            # Формируем HTML контент сообщений
            messages_html = ""
            img_counter = 0
            
            for msg in messages:
                sender = "Клиент" if msg.get("is_user", True) else "Бот"
                css_class = "user" if msg.get("is_user", True) else "bot"
                content = msg.get("content", "") or ""
                time_str = ""
                if msg.get("created_at"):
                    try:
                        dt = datetime.fromisoformat(str(msg["created_at"]).replace('Z', '+00:00'))
                        time_str = dt.strftime("%H:%M")
                    except:
                        pass
                
                # Проверяем есть ли изображение в сообщении
                image_html = ""
                if msg.get("image"):
                    img_path = msg.get("image")
                    if img_path and os.path.exists(img_path):
                        cid = f"image{img_counter}"
                        image_cid_map[img_path] = cid
                        image_html = f'<div style="margin-top: 10px;"><img src="cid:{cid}" style="max-width: 300px; border-radius: 8px;"></div>'
                        img_counter += 1

                att_html = ""
                if msg.get("attachment"):
                    ap = msg.get("attachment")
                    if ap and os.path.exists(ap):
                        fname = os.path.basename(ap)
                        att_html = f'<div style="margin-top: 8px;">📎 Вложение: {fname} (файл также прикреплён к письму)</div>'
                
                messages_html += f"""
                <div class="message {css_class}">
                    <div class="label">{sender} {time_str}</div>
                    <div>{content}</div>
                    {image_html}
                    {att_html}
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
            
            # Создаем сообщение с поддержкой вложений
            msg = MIMEMultipart('related')
            msg['Subject'] = subject
            msg['From'] = f"{EMAIL_CREDENTIALS['sender_name']} <{EMAIL_CREDENTIALS['sender_email']}>"
            msg['To'] = NOTIFICATION_RECIPIENTS["main_recipient"]
            
            # Добавляем CC если есть
            cc_recipients = NOTIFICATION_RECIPIENTS.get("cc_recipients", [])
            if cc_recipients:
                msg['Cc'] = ", ".join(cc_recipients)
            
            # Создаём альтернативную часть для HTML
            msg_alternative = MIMEMultipart('alternative')
            msg.attach(msg_alternative)
            
            # Прикрепляем HTML
            html_part = MIMEText(html_body, 'html', 'utf-8')
            msg_alternative.attach(html_part)
            
            # Прикрепляем inline изображения
            for img_path, cid in image_cid_map.items():
                try:
                    with open(img_path, 'rb') as img_file:
                        img_data = img_file.read()
                        
                    # Определяем тип изображения
                    ext = os.path.splitext(img_path)[1].lower()
                    subtype = {
                        '.jpg': 'jpeg',
                        '.jpeg': 'jpeg',
                        '.png': 'png',
                        '.gif': 'gif',
                        '.webp': 'webp',
                    }.get(ext, 'jpeg')
                    
                    img_attachment = MIMEImage(img_data, _subtype=subtype)
                    img_attachment.add_header('Content-ID', f'<{cid}>')
                    img_attachment.add_header('Content-Disposition', 'inline', filename=os.path.basename(img_path))
                    msg.attach(img_attachment)
                    
                except Exception as e:
                    print(f"[WARNING] Failed to attach image {img_path}: {e}")
            
            # Прикрепляем дополнительные изображения как вложения
            for img_path in image_paths:
                if img_path not in image_cid_map and os.path.exists(img_path):
                    try:
                        with open(img_path, 'rb') as img_file:
                            img_data = img_file.read()
                        
                        attachment = MIMEBase('application', 'octet-stream')
                        attachment.set_payload(img_data)
                        encoders.encode_base64(attachment)
                        attachment.add_header(
                            'Content-Disposition',
                            'attachment',
                            filename=os.path.basename(img_path)
                        )
                        msg.attach(attachment)
                    except Exception as e:
                        print(f"[WARNING] Failed to attach file {img_path}: {e}")

            # PDF и прочие вложения из сообщений (не дублируем уже inline-картинки)
            attached_paths = set(image_cid_map.keys())
            for entry in messages:
                ap = entry.get("attachment")
                if not ap or not os.path.exists(ap) or ap in attached_paths:
                    continue
                attached_paths.add(ap)
                try:
                    with open(ap, 'rb') as f:
                        data = f.read()
                    sub = 'pdf' if ap.lower().endswith('.pdf') else 'octet-stream'
                    part = MIMEBase('application', sub)
                    part.set_payload(data)
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=os.path.basename(ap),
                    )
                    msg.attach(part)
                except Exception as e:
                    print(f"[WARNING] Failed to attach PDF {ap}: {e}")
            
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

