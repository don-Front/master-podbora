# -*- coding: utf-8 -*-
"""
Конфигурация для отправки email-уведомлений о заявках на оборудование
"""

SEND_EMAIL = True

SMTP_SERVER = "smtp.mail.ru"
SMTP_PORT = 465

SENDER_EMAIL = "turbopodbor@mail.ru"
SENDER_PASSWORD = "qNbTejrNOJjF9qiDXwpK"

MANAGER_EMAIL = "d.shamray@turbo-don.ru"
RECEIVER_EMAIL = MANAGER_EMAIL
RECIPIENT_EMAIL = MANAGER_EMAIL

CC_EMAILS = []

EQUIPMENT_EMAIL_ROUTES = {
    "modular": {"to": MANAGER_EMAIL, "cc": []},
    "verification": {"to": MANAGER_EMAIL, "cc": []},
    "pressure": {"to": MANAGER_EMAIL, "cc": []},
    "household": {"to": MANAGER_EMAIL, "cc": []},
    "spu": {"to": MANAGER_EMAIL, "cc": []},
    "verification-liquid": {"to": MANAGER_EMAIL, "cc": []},
    "technical-gases": {"to": MANAGER_EMAIL, "cc": []},
}

EMAIL_SUBJECT_TEMPLATE = "Заявка на продукцию от {fullname}"

EMAIL_BODY_TEMPLATE = """
Новая заявка на блочно-модульные изделия:

═══════════════════════════════════════
ДАННЫЕ ЗАЯВИТЕЛЯ
═══════════════════════════════════════
ФИО:          {fullname}
Организация:  {organization}
Должность:    {position}
Телефон:      {phone}
Email:        {email}

═══════════════════════════════════════
ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ
═══════════════════════════════════════
{comment_section}

═══════════════════════════════════════
ТЕХНИЧЕСКОЕ ЗАДАНИЕ
═══════════════════════════════════════
Файл прикреплен к письму: {filename}
Размер файла: {filesize} МБ

Дата и время заявки: {timestamp}

---
Автоматическое уведомление из системы подбора оборудования
"""
