# -*- coding: utf-8 -*-
"""
Дерево подсказок чат-бота на основе UML диаграммы.
Каждый узел содержит:
- id: уникальный идентификатор состояния
- bot_message: сообщение бота при входе в это состояние
- hints: список подсказок (кнопок) для пользователя
- next_state: следующее состояние при выборе подсказки или вводе текста
- expects_input: ожидает ли состояние текстовый ввод от пользователя
- is_final: является ли состояние финальным
- hints_only: только кнопки-подсказки, поле ввода на фронте отключается
"""

HINTS_TREE = {
    # Начальное состояние
    "start": {
        "id": "start",
        "bot_message": "Здравствуйте! Чем я могу Вам помочь?",
        "hints": [
            {"text": "Подбор оборудования", "next_state": "equipment_pick"},
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Обратная связь", "next_state": "feedback_pick"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": False,
    },

    # Подменю: расходомеры (заказ по PDF) и поверочные установки (веб-сценарий)
    "equipment_pick": {
        "id": "equipment_pick",
        "bot_message": (
            "Подбор оборудования: выберите направление — расходомеры (заявка по PDF) "
            "или поверочные установки (сценарий выбора среды и параметров)."
        ),
        "hints": [
            {"text": "Расходомеры", "next_state": "order_pdf_request"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Бытовые счетчики газа", "next_state": "equipment_household_gas_dev"},
            {"text": "Плотномеры", "next_state": "equipment_densitometers_dev"},
            {"text": "Датчики давления", "next_state": "equipment_pressure_sensors_dev"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },

    "equipment_household_gas_dev": {
        "id": "equipment_household_gas_dev",
        "bot_message": "Выберите бытовые счётчики газа в прайс-листе и нажмите «Оставить заявку».",
        "hints": [],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "household_gas_fullname": {
        "id": "household_gas_fullname",
        "bot_message": "Укажите, пожалуйста, ваше полное ФИО (фамилия, имя и отчество).",
        "hints": [],
        "expects_input": True,
        "next_state": "household_gas_contact",
        "is_final": False,
        "show_back": True,
    },
    "household_gas_contact": {
        "id": "household_gas_contact",
        "bot_message": (
            "Укажите адрес электронной почты или номер телефона для связи "
            "(телефон — в российском формате, например +7 903 123-45-67 или 89031234567)."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "household_gas_organization",
        "is_final": False,
        "show_back": True,
    },
    "household_gas_organization": {
        "id": "household_gas_organization",
        "bot_message": "Укажите организацию. Если заявки от физического лица — отправьте «-» или «нет».",
        "hints": [],
        "expects_input": True,
        "next_state": "household_gas_comment",
        "is_final": False,
        "show_back": True,
    },
    "household_gas_comment": {
        "id": "household_gas_comment",
        "bot_message": "Напишите комментарий к заявке (например: «Нужна поставка 10 шт.»). Если комментариев нет — отправьте «-» или «нет».",
        "hints": [],
        "expects_input": True,
        "next_state": "household_gas_after_submit",
        "is_final": False,
        "show_back": True,
    },
    "household_gas_after_submit": {
        "id": "household_gas_after_submit",
        "bot_message": "Заявка по бытовым счётчикам газа принята. В ближайшее время с вами свяжется менеджер.",
        "hints": [],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "equipment_densitometers_dev": {
        "id": "equipment_densitometers_dev",
        "bot_message": "Раздел «Плотномеры» в разработке.",
        "hints": [],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "equipment_pressure_sensors_dev": {
        "id": "equipment_pressure_sensors_dev",
        "bot_message": "Раздел «Датчики давления» в разработке.",
        "hints": [],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },

    # Подменю: техподдержка и претензии
    "feedback_pick": {
        "id": "feedback_pick",
        "bot_message": (
            "Обратная связь: выберите раздел — техническая поддержка по оборудованию "
            "или претензия по качеству продукции / сервиса."
        ),
        "hints": [
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },

    # ===== ОФОРМЛЕНИЕ ЗАКАЗА: после выбора — просьба прислать PDF; дальше только загрузка файла =====
    "order_pdf_request": {
        "id": "order_pdf_request",
        "bot_message": (
            "Пришлите, пожалуйста, файл в формате PDF с описанием характеристик необходимого оборудования "
            "(наименование, модель, параметры, количество, контакты для связи — по желанию)."
        ),
        "hints": [],
        "expects_input": False,
        "next_state": "order_final",
        "is_final": False,
        "show_back": True,
    },
    # Уточнение полей, если в JSON после LLM остались null/0
    "order_specs_clarify": {
        "id": "order_specs_clarify",
        "bot_message": "Нужно уточнить несколько параметров по спецификации. Ответьте на вопросы по одному.",
        "hints": [],
        "expects_input": True,
        "is_final": False,
        "show_back": True,
        "next_state": "order_final",
    },
    "order_final": {
        "id": "order_final",
        "bot_message": (
            "Спасибо! Заявка на оформление заказа принята. В ближайшее время с Вами свяжется менеджер. "
            "Срочные вопросы: +7 (863) 203-77-80 (доб. 1080 или 1108)."
        ),
        "hints": [
            {"text": "Расходомеры", "next_state": "order_pdf_request"},
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },
    # Запрос цены по прибору со слайдера: телефон -> почта -> код с почты -> order_final
    "equipment_price_phone": {
        "id": "equipment_price_phone",
        "bot_message": (
            "Укажите номер телефона для связи (российский формат, например +7 903 123-45-67 или 89031234567)."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "equipment_price_email",
        "is_final": False,
        "show_back": True,
    },
    "equipment_price_email": {
        "id": "equipment_price_email",
        "bot_message": (
            "Укажите адрес электронной почты для верификации — на него мы отправим проверочный код."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "equipment_price_verify_code",
        "is_final": False,
        "show_back": True,
    },
    "equipment_price_verify_code": {
        "id": "equipment_price_verify_code",
        "bot_message": (
            "На указанную почту отправлен код подтверждения. Введите шестизначный код из письма."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "order_final",
        "is_final": False,
        "show_back": True,
    },
    # ===== ПРОДАЖА ОБОРУДОВАНИЯ =====
    "sales": {
        "id": "sales",
        "bot_message": "Подскажите пожалуйста, Вас интересует промышленное оборудование или бытовые счетчики?",
        "hints": [
            {"text": "Промышленное оборудование", "next_state": "sales_industrial"},
            {"text": "Бытовые счетчики", "next_state": "sales_household"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "sales_industrial": {
        "id": "sales_industrial",
        "bot_message": "Напишите наименование Вашей организации, тип оборудования, его модель, объем закупок.",
        "hints": [],
        "expects_input": True,
        "next_state": "sales_contact",
        "is_final": False,
        "show_back": True,
    },
    "sales_household": {
        "id": "sales_household",
        "bot_message": "Напишите наименование Вашей организации, тип оборудования, его модель, объем закупок.",
        "hints": [],
        "expects_input": True,
        "next_state": "sales_contact",
        "is_final": False,
        "show_back": True,
    },
    "sales_contact": {
        "id": "sales_contact",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "sales_final",
        "is_final": False,
        "show_back": True,
    },
    "sales_final": {
        "id": "sales_final",
        "bot_message": "Спасибо за Ваше обращение! В скором времени с Вами свяжется наш менеджер! Если у Вас срочный вопрос, то можете обратиться по номеру: +7 (863) 203-77-80 (доб. 1080 или 1108)",
        "hints": [
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },
    
    # ===== ПОВЕРКА =====
    "verification": {
        "id": "verification",
        "bot_message": "Подскажите пожалуйста, Вас интересует поверка собственного оборудования или стороннее оборудование?",
        "hints": [
            {"text": "Собственное оборудование", "next_state": "verification_own"},
            {"text": "Стороннее оборудование", "next_state": "verification_third"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "verification_own": {
        "id": "verification_own",
        "bot_message": "Напишите заводской номер, тип оборудования.",
        "hints": [],
        "expects_input": True,
        "next_state": "verification_contact",
        "is_final": False,
        "show_back": True,
    },
    "verification_third": {
        "id": "verification_third",
        "bot_message": "Напишите заводской номер, тип оборудования.",
        "hints": [],
        "expects_input": True,
        "next_state": "verification_contact",
        "is_final": False,
        "show_back": True,
    },
    "verification_contact": {
        "id": "verification_contact",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "verification_final",
        "is_final": False,
        "show_back": True,
    },
    "verification_final": {
        "id": "verification_final",
        "bot_message": "Спасибо за Ваше обращение! В скором времени с Вами свяжется наш менеджер! Если у Вас срочный вопрос, то можете обратиться по номеру: +7 (863) 203-77-80 (доб. 1080 или 1108)",
        "hints": [
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },

    # ===== ПОВЕРОЧНЫЕ УСТАНОВКИ (веб-сценарий) =====
    "verification_installations": {
        "id": "verification_installations",
        "bot_message": "Выберите среду поверочной установки",
        "hints": [
            {"text": "Газ 🔥", "next_state": "verification_installations_gas"},
            {"text": "Жидкость 💧", "next_state": "verification_installations_liquid"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
        "hints_only": True,
    },
    "verification_installations_gas": {
        "id": "verification_installations_gas",
        "bot_message": "",
        "hints": [],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
        "hints_only": True,
    },
    "verification_installations_gas_application": {
        "id": "verification_installations_gas_application",
        "bot_message": (
            "Укажите, пожалуйста, ваше полное ФИО (фамилия, имя и отчество) одной строкой, как в паспорте."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "verification_installations_gas_application_contact",
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_gas_application_contact": {
        "id": "verification_installations_gas_application_contact",
        "bot_message": (
            "Укажите адрес электронной почты или номер телефона для связи "
            "(телефон — в российском формате, например +7 903 123-45-67 или 89031234567)."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "verification_installations_gas_application_tz",
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_gas_application_tz": {
        "id": "verification_installations_gas_application_tz",
        "bot_message": (
            "Загрузите техническое задание одним файлом. Допустимые форматы: PDF, DOC, DOCX, TXT, ZIP, RAR "
            "(размер до 10 МБ). Документ можно подписать электронной подписью или вручную — по желанию. "
            "Если прикладывать ТЗ не планируете, нажмите «Далее»."
        ),
        "hints": [{"text": "Далее", "next_state": "verification_installations_gas_application_tz_comments"}],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_gas_application_tz_comments": {
        "id": "verification_installations_gas_application_tz_comments",
        "bot_message": (
            "Напишите, пожалуйста, любые комментарии к техническому заданию (уточнения, пожелания, вопросы). "
            "Если комментариев нет — отправьте «-» или «нет»."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "verification_installations_gas_application_after_tz",
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_gas_application_after_tz": {
        "id": "verification_installations_gas_application_after_tz",
        "bot_message": (
            "Спасибо! Заявка по подобранной поверочной установке (газ) принята. Скоро с Вами свяжется менеджер."
        ),
        "hints": [],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_liquid": {
        "id": "verification_installations_liquid",
        "bot_message": (
            "Укажите, пожалуйста, ваше полное ФИО (фамилия, имя и отчество) одной строкой, как в паспорте."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "verification_installations_liquid_contact",
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_liquid_contact": {
        "id": "verification_installations_liquid_contact",
        "bot_message": (
            "Укажите адрес электронной почты или номер телефона для связи "
            "(телефон — в российском формате, например +7 903 123-45-67 или 89031234567)."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "verification_installations_liquid_tz",
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_liquid_tz": {
        "id": "verification_installations_liquid_tz",
        "bot_message": (
            "Загрузите техническое задание одним файлом. Допустимые форматы: PDF, DOC, DOCX, TXT, ZIP, RAR "
            "(размер до 10 МБ). Документ можно подписать электронной подписью или вручную — по желанию. "
            "Если прикладывать ТЗ не планируете, нажмите «Далее»."
        ),
        "hints": [{"text": "Далее", "next_state": "verification_installations_liquid_tz_comments"}],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_liquid_tz_comments": {
        "id": "verification_installations_liquid_tz_comments",
        "bot_message": (
            "Напишите, пожалуйста, любые комментарии к техническому заданию (уточнения, пожелания, вопросы). "
            "Если комментариев нет — отправьте «-» или «нет»."
        ),
        "hints": [],
        "expects_input": True,
        "next_state": "verification_installations_liquid_after_tz",
        "is_final": False,
        "show_back": True,
    },
    "verification_installations_liquid_after_tz": {
        "id": "verification_installations_liquid_after_tz",
        "bot_message": (
            "Дальнейшие шаги веб-сценария для среды «жидкость» будут доступны на сайте."
        ),
        "hints": [],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    
    # ===== ПУСКО-НАЛАДОЧНЫЕ РАБОТЫ =====
    "commissioning": {
        "id": "commissioning",
        "bot_message": "Напишите: заводской номер прибора, Ваше имя, адрес объекта, требования к допуску на объект.",
        "hints": [],
        "expects_input": True,
        "next_state": "commissioning_contact",
        "is_final": False,
        "show_back": True,
    },
    "commissioning_contact": {
        "id": "commissioning_contact",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "commissioning_final",
        "is_final": False,
        "show_back": True,
    },
    "commissioning_final": {
        "id": "commissioning_final",
        "bot_message": "Спасибо большое, перезвоните по данному номеру +7 (928) 960-92-42",
        "hints": [
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },
    
    # ===== ТЕХНИЧЕСКАЯ ПОДДЕРЖКА =====
    "tech_support": {
        "id": "tech_support",
        "bot_message": "Подскажите пожалуйста, по какому оборудованию Вас интересует тех. поддержка?",
        "hints": [
            {"text": "Промышленное оборудование", "next_state": "tech_support_industrial"},
            {"text": "Бытовые счетчики", "next_state": "tech_support_household"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "tech_support_industrial": {
        "id": "tech_support_industrial",
        "bot_message": "Напишите пожалуйста: модель, заводской номер, а также, опишите проблему или напишите Ваш вопрос.",
        "hints": [],
        "expects_input": True,
        "next_state": "tech_support_contact",
        "is_final": False,
        "show_back": True,
    },
    "tech_support_household": {
        "id": "tech_support_household",
        "bot_message": "Напишите пожалуйста: модель, заводской номер, а также, опишите проблему или напишите Ваш вопрос.",
        "hints": [],
        "expects_input": True,
        "next_state": "tech_support_contact",
        "is_final": False,
        "show_back": True,
    },
    "tech_support_contact": {
        "id": "tech_support_contact",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "tech_support_final",
        "is_final": False,
        "show_back": True,
    },
    "tech_support_final": {
        "id": "tech_support_final",
        "bot_message": "Спасибо большое, перезвоните по данному номеру +7 (928) 960-92-42",
        "hints": [
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },
    
    # ===== ПРЕТЕНЗИИ =====
    "claims": {
        "id": "claims",
        "bot_message": "Подскажите пожалуйста какое оборудование?",
        "hints": [
            {"text": "Промышленное оборудование", "next_state": "claims_industrial"},
            {"text": "Бытовые счетчики", "next_state": "claims_household"},
        ],
        "expects_input": False,
        "is_final": False,
        "show_back": True,
    },
    "claims_industrial": {
        "id": "claims_industrial",
        "bot_message": "Напишите, пожалуйста, № договора/спецификации, № ОЛ, заводской номер прибора, описание несоответствий, фотографии несоответствий, акт с фиксацией несоответствий.",
        "hints": [],
        "expects_input": True,
        "next_state": "claims_contact",
        "is_final": False,
        "show_back": True,
    },
    "claims_household": {
        "id": "claims_household",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "claims_final",
        "is_final": False,
        "show_back": True,
    },
    "claims_contact": {
        "id": "claims_contact",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "claims_final",
        "is_final": False,
        "show_back": True,
    },
    "claims_final": {
        "id": "claims_final",
        "bot_message": "Спасибо большое, перезвоните по данному номеру +7 (928) 960-92-42",
        "hints": [
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },
    
    # ===== ОТКЛИК НА ВАКАНСИЮ =====
    "vacancy": {
        "id": "vacancy",
        "bot_message": "Напишите вакансию и Ваш опыт работы. А также, вставьте ссылку на ваше резюме на hh.ru",
        "hints": [],
        "expects_input": True,
        "next_state": "vacancy_contact",
        "is_final": False,
        "show_back": True,
    },
    "vacancy_contact": {
        "id": "vacancy_contact",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "vacancy_final",
        "is_final": False,
        "show_back": True,
    },
    "vacancy_final": {
        "id": "vacancy_final",
        "bot_message": "Спасибо большое за отклик! В скором времени с Вами свяжется наш рекрутер.",
        "hints": [
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },
    
    # ===== ДРУГОЕ =====
    "other": {
        "id": "other",
        "bot_message": "Напишите ваш вопрос.",
        "hints": [],
        "expects_input": True,
        "next_state": "other_contact",
        "is_final": False,
        "show_back": True,
    },
    "other_contact": {
        "id": "other_contact",
        "bot_message": "Напишите Ваш номер телефона и/или Ваш email для связи с Вами.",
        "hints": [],
        "expects_input": True,
        "next_state": "other_final",
        "is_final": False,
        "show_back": True,
    },
    "other_final": {
        "id": "other_final",
        "bot_message": "Спасибо за Ваше обращение! Скоро с Вами свяжется наш менеджер. Если вопрос срочный, то вы можете позвонить по номеру: +7 (863) 203-77-80 (доб. 1134)",
        "hints": [
            {"text": "Продажа оборудования", "next_state": "sales"},
            {"text": "Поверка", "next_state": "verification"},
            {
                "text": "Поверочные установки",
                "next_state": "verification_installations",
            },
            {"text": "Пуско-наладочные работы", "next_state": "commissioning"},
            {"text": "Техническая поддержка", "next_state": "tech_support"},
            {"text": "Претензии", "next_state": "claims"},
            {"text": "Отклик на вакансию", "next_state": "vacancy"},
            {"text": "Другое", "next_state": "other"},
        ],
        "expects_input": False,
        "is_final": True,
        "show_back": False,
    },
    
    # Специальное состояние для режима свободного общения с AI
    "free_chat": {
        "id": "free_chat",
        "bot_message": None,  # Ответ генерируется AI
        "hints": [],
        "expects_input": True,
        "is_final": False,
        "show_back": True,
    },
}


def get_state(state_id: str) -> dict:
    """Получить состояние по ID"""
    return HINTS_TREE.get(state_id, HINTS_TREE["start"])


def get_next_state(current_state_id: str, hint_text: str = None) -> str:
    """Получить следующее состояние на основе текущего и выбранной подсказки"""
    current = get_state(current_state_id)
    
    if hint_text:
        # Ищем подсказку с таким текстом
        for hint in current.get("hints", []):
            if hint["text"] == hint_text:
                return hint["next_state"]
    
    # Если подсказка не найдена или был свободный ввод
    return current.get("next_state", current_state_id)


def get_parent_state(state_id: str) -> str:
    """Получить родительское состояние для кнопки 'Вернуться'"""
    # Маппинг состояний на их родителей
    parent_map = {
        # Подбор оборудования (подменю стартового экрана)
        "equipment_pick": "start",
        "equipment_household_gas_dev": "equipment_pick",
        "household_gas_fullname": "equipment_household_gas_dev",
        "household_gas_contact": "household_gas_fullname",
        "household_gas_organization": "household_gas_contact",
        "household_gas_comment": "household_gas_organization",
        "household_gas_after_submit": "household_gas_comment",
        "equipment_densitometers_dev": "equipment_pick",
        "equipment_pressure_sensors_dev": "equipment_pick",
        "feedback_pick": "start",

        # Продажа
        "sales": "start",
        "sales_industrial": "sales",
        "sales_household": "sales",
        "sales_contact": "sales",
        
        # Поверка
        "verification": "start",
        "verification_own": "verification",
        "verification_third": "verification",
        "verification_contact": "verification",
        "verification_installations": "equipment_pick",
        "verification_installations_gas": "verification_installations",
        "verification_installations_gas_application": "verification_installations_gas",
        "verification_installations_gas_application_contact": "verification_installations_gas_application",
        "verification_installations_gas_application_tz": "verification_installations_gas_application_contact",
        "verification_installations_gas_application_tz_comments": "verification_installations_gas_application_tz",
        "verification_installations_gas_application_after_tz": "verification_installations_gas_application_tz_comments",
        "verification_installations_liquid": "verification_installations",
        "verification_installations_liquid_contact": "verification_installations_liquid",
        "verification_installations_liquid_tz": "verification_installations_liquid_contact",
        "verification_installations_liquid_tz_comments": "verification_installations_liquid_tz",
        "verification_installations_liquid_after_tz": "verification_installations_liquid_tz_comments",
        
        # Пуско-наладка
        "commissioning": "start",
        "commissioning_contact": "commissioning",
        
        # Тех. поддержка
        "tech_support": "feedback_pick",
        "tech_support_industrial": "tech_support",
        "tech_support_household": "tech_support",
        "tech_support_contact": "tech_support",
        
        # Претензии
        "claims": "feedback_pick",
        "claims_industrial": "claims",
        "claims_household": "claims",
        "claims_contact": "claims",
        
        # Вакансии
        "vacancy": "start",
        "vacancy_contact": "vacancy",
        
        # Другое
        "other": "start",
        "other_contact": "other",
        
        # Свободный чат
        "free_chat": "start",

        # Оформление заказа
        "order_pdf_request": "equipment_pick",
        "order_specs_clarify": "order_pdf_request",
        "equipment_price_phone": "order_final",
        "equipment_price_email": "equipment_price_phone",
        "equipment_price_verify_code": "equipment_price_email",
    }
    return parent_map.get(state_id, "start")

