# -*- coding: utf-8 -*-
"""
Конфигурация SMTP для отправки email уведомлений.
Измените эти настройки под вашу почту.
"""

SMTP_CONFIG = {
    "host": "smtp.gmail.com",
    
    "port": 587,
    
    "use_tls": True,
    "use_ssl": False,
    
    "timeout": 30,
}

EMAIL_CREDENTIALS = {
    "sender_email": "mangasaryangeneral@gmail.com",
    
    "sender_password": "uuzlbxoggyojzihd",
    
    "sender_name": "Turbo-Don Чат-бот",
}

# ===== ПОЛУЧАТЕЛИ УВЕДОМЛЕНИЙ =====
NOTIFICATION_RECIPIENTS = {
    # Основной email для получения уведомлений о новых обращениях
    "main_recipient": "d.shamray@turbo-don.ru",

    # Оператор техподдержки (стилизованное письмо при tech_support_final)
    "tech_support_operator": "sktb_otp2@turbo-don.ru",
    
    # Дополнительные получатели (опционально)
    "cc_recipients": [
        # "sales@turbo-don.ru",
        # "support@turbo-don.ru",
    ],
}

# ===== НАСТРОЙКИ ВАЛИДАЦИИ EMAIL =====
EMAIL_VALIDATION = {
    # Проверять существование домена (MX записи)
    "check_mx": True,
    
    # Проверять существование email через SMTP (может быть заблокировано некоторыми серверами)
    "verify_email": False,
    
    # Таймаут проверки в секундах
    "timeout": 10,
}

# ===== ШАБЛОНЫ ПИСЕМ =====
EMAIL_TEMPLATES = {
    # Тема письма (можно использовать {category} для подстановки категории обращения)
    "subject": "Новое обращение в чат-бот: {category}",
    
    # Шаблон HTML письма
    "html_template": """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #1e40af; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f9fafb; padding: 20px; border: 1px solid #e5e7eb; }}
        .message {{ background: white; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #3b82f6; }}
        .message.user {{ border-left-color: #10b981; }}
        .message.bot {{ border-left-color: #6366f1; }}
        .label {{ font-weight: bold; color: #6b7280; font-size: 12px; margin-bottom: 5px; }}
        .contact-info {{ background: #dbeafe; padding: 15px; border-radius: 8px; margin-top: 20px; }}
        .footer {{ text-align: center; color: #9ca3af; font-size: 12px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">📩 Новое обращение в чат-бот</h2>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">Категория: {category}</p>
        </div>
        <div class="content">
            <div class="contact-info">
                <h3 style="margin-top: 0;">📋 Контактная информация</h3>
                <p><strong>Email клиента:</strong> {client_email}</p>
                <p><strong>Телефон:</strong> {client_phone}</p>
                <p><strong>IP адрес:</strong> {ip_address}</p>
                <p><strong>Дата обращения:</strong> {date}</p>
            </div>
            
            <h3>💬 История диалога</h3>
            {messages}
        </div>
        <div class="footer">
            <p>Это автоматическое уведомление от чат-бота Turbo-Don</p>
        </div>
    </div>
</body>
</html>
""",
}

