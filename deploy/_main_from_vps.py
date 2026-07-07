from fastapi import FastAPI, Request, HTTPException, Depends, Form, UploadFile, File
from starlette.background import BackgroundTask

from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator
from typing import Optional, Dict, Any, List, Literal
import json
import os
import sys
import uvicorn
from datetime import datetime
from pathlib import Path
import hashlib
import secrets
import math
import uuid
import asyncio
import tempfile
from urllib.parse import quote
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, status
import httpx
import logging
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from price_estimate import EstimatePriceRequest, EstimatePriceResponse, estimate_from_request
from tkp_accessories import (
    TkpAccessoriesRequest,
    TkpAccessoriesResponse,
    tkp_accessories_from_request,
    tkp_discovery_message,
)
from tkp_pdf import (
    TkpPdfRequest,
    build_tkp_pdf_bytes,
    tkp_pdf_attachment_filename,
    tkp_pdf_discovery,
)


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

# Настройка кодировки для вывода в консоль (Windows fix)
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_local_env() -> None:
    """Минимальная загрузка .env для локального запуска без внешних зависимостей."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as exc:
        logger.warning("Не удалось прочитать .env: %s", exc)


load_local_env()

# Коды верификации — verification_codes_store.py (общий файл для всех workers)
VERIFICATION_CODE_TTL = 300  # 5 минут в секундах
from verification_codes_store import (
    delete_entry as _vc_delete,
    get_entry as _vc_get,
    mark_verified as _vc_mark_verified,
    purge_expired as _vc_purge,
    set_code as _vc_set,
)


# Модели данных
class EquipmentParams(BaseModel):
    medium: str
    application: Optional[str] = None
    gas_type: Optional[str] = None
    flow_min: Optional[str] = None  # Изменено на str для поддержки запятых
    flow_max: Optional[str] = None  # Изменено на str для поддержки запятых
    flow_unit: Optional[str] = None  # "м³/ч", "кг/ч", "ст.м³/ч"
    flow_conditions: Optional[str] = None
    pressure_min: Optional[str] = None  # Изменено на str для поддержки запятых
    pressure_max: Optional[str] = None  # Изменено на str для поддержки запятых
    pressure_unit: Optional[str] = None
    temperature_min: Optional[str] = None  # Изменено на str для поддержки запятых
    temperature_max: Optional[str] = None  # Изменено на str для поддержки запятых
    temperature_unit: Optional[str] = None
    ambient_temp_min: Optional[str] = None  # Температура окружающей среды мин
    ambient_temp_max: Optional[str] = None  # Температура окружающей среды макс
    ambient_temperature_min: Optional[str] = None  # Для обратной совместимости
    ambient_temperature_max: Optional[str] = None  # Для обратной совместимости
    accuracy: Optional[str] = None  # Изменено на str для поддержки запятых
    diameter: Optional[str] = None  # Изменено на str для поддержки запятых
    density_min: Optional[str] = None  # Изменено на str для поддержки запятых
    density_max: Optional[str] = None  # Изменено на str для поддержки запятых
    gas_conditions: Optional[str] = None  # для газовых условий
    user_id: Optional[str] = None  # Для привязки к аккаунту 1С

class UserAuth(BaseModel):
    username: str
    password: str
    system_1c_id: Optional[str] = None

class QuestionnaireRequest(BaseModel):
    equipment_id: str
    equipment_name: str
    search_params: Dict[str, Any]
    user_login: Optional[str] = None  # Логин пользователя для передачи в 1С
    equipment_type: Optional[str] = "flowmeter"  # Тип оборудования: flowmeter или densitometer

class SearchResult(BaseModel):
    equipment: List[Dict[str, Any]]
    total_count: int
    search_params: Dict[str, Any]

# Модели для работы с 1С
class LoginData(BaseModel):
    login: str = Field(..., description="Логин пользователя")

class APIRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: str = Field(..., description="Тип данных")
    data: Dict[Any, Any] = Field(..., description="Данные")
    timestamp: Optional[str] = Field(None, description="Временная метка")
    # Некоторые клиенты (браузер) кладут токен в JSON; стандарт — заголовок Authorization
    authorization: Optional[str] = Field(
        default=None,
        description="Опционально: Bearer token (предпочтительно передавать в HTTP-заголовке)",
        validation_alias=AliasChoices("Authorization", "authorization"),
    )

class APIResponse(BaseModel):
    status: str = Field(..., description="Статус ответа")
    message: str = Field(..., description="Сообщение")
    received_at: str = Field(..., description="Время получения")
    data_type: Optional[str] = Field(None, description="Тип данных")
    equipment: Optional[List[Dict[str, Any]]] = Field(
        None, description="Подобранное оборудование (при type=equipment_params)"
    )
    total_count: Optional[int] = Field(
        None, description="Количество подобранных позиций (при type=equipment_params)"
    )


class EquipmentCardForPrice(BaseModel):
    """Карточка оборудования с фронта для выдачи файла прайса (см. ответ /api/1c/data)."""

    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(..., description="Идентификатор из data.json, напр. ufg2")
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    image: Optional[str] = None
    specs: Optional[Dict[str, Any]] = None
    params: Optional[Dict[str, Any]] = None
    recommended_diameter: Optional[str] = None
    authorization: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("Authorization", "authorization"),
    )

# Инициализация FastAPI
app = FastAPI(
    title="Система подбора оборудования",
    description="Веб-приложение для подбора газового и жидкостного оборудования",
    version="1.0.0"
)

# Настройка CORS — список разрешённых источников (origin = протокол + хост + порт)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://turbo-don.ru",
        "https://master-podbor.ru",
        "https://www.master-podbor.ru",
        "http://master-podbor.ru",
        "http://www.master-podbor.ru",
        "http://192.168.5.96:3000",   # внешняя система, шлёт данные по API
        "http://192.168.2.17:3000",   # локальный фронтенд по сетевому IP
        "http://192.168.2.41:3000",   # локальный фронтенд по текущему сетевому IP
        "http://192.168.2.127:8000",  # этот же сервер (локальные тесты)
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ],
    # Любой хост во внутренних подсетях (CRA / другие клиенты по IP:порт из LAN)
    allow_origin_regex=(
        r"^http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$"
    ),
    allow_credentials=True,
    allow_methods=["*"],  # Разрешить все HTTP методы
    allow_headers=["*"],  # Разрешить все заголовки
)

# Конфигурация безопасности для 1С API
API_TOKEN = os.getenv("API_TOKEN", "change-me")
ONE_C_AUTH_TOKEN = os.getenv("ONE_C_AUTH_TOKEN", "")
security = HTTPBearer()

# Статические файлы и шаблоны
# Получаем абсолютный путь к директории проекта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRAISES_DIR = Path(BASE_DIR) / "прайсы"
# id оборудования (data.json) → имя файла прайса в каталоге прайсы/
EQUIPMENT_ID_TO_PRICE_FILENAME: Dict[str, str] = {
    "ufg2": "05-2026.01.20. Приказ № ГК00-000006 Прайс Основной 4.js",
    "ufgfc1": "2026.01.20. Приказ № ГК00-000004 Прайс Основной 2 С-корпус.js",
    "tfgs1": "07-2026.01.20. Приказ № ГК00-000008 Прайс Основной 6.js",
    "tfgh1": "07-2026.01.20. Приказ № ГК00-000008 Прайс Основной 6.js",
    "ufgh1": "07-2026.01.20. Приказ № ГК00-000008 Прайс Основной 6.js",
    "gfg2": "07-2026.01.20. Приказ № ГК00-000008 Прайс Основной 6.js",
    "ufl1": "01-2026.01.19. Приказ № ГК00-000003 Прайс Основной 1.js",
    "cfm1": "04-2026.01.20. Приказ № ГК00-000005 Прайс Основной 3.js",
    "udm1": "07-2026.01.20. Приказ № ГК00-000008 Прайс Основной 6.js",
}
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Картинки из data.json: поле вида «equipment/foo.png» → файл на диске static/equipment/foo.png
# и то же самое использует SPA: image_url = /static/{image}
os.makedirs(os.path.join(STATIC_DIR, "equipment"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Маршрут для data.json
@app.get("/data.json")
async def get_data_json():
    """Возвращает данные оборудования из JSON файла"""
    return equipment_db

# Загрузка базы данных оборудования
def load_equipment_db():
    try:
        # Получаем путь к директории, где находится main.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_path = os.path.join(current_dir, 'data.json')
        
        if not os.path.exists(data_path):
            logger.error(f"Файл data.json не найден по пути: {data_path}")
            return {"gas": {"industrial": {"natural": [], "technological": []}, "utility": []}, "liquid": {"industrial": []}}
        
        with open(data_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл data.json не найден по пути: {data_path}")
        return {"gas": {"industrial": {"natural": [], "technological": []}, "utility": []}, "liquid": {"industrial": []}}
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON в файле data.json: {e}")
        return {"gas": {"industrial": {"natural": [], "technological": []}, "utility": []}, "liquid": {"industrial": []}}
    except Exception as e:
        logger.error(f"Неожиданная ошибка при загрузке data.json: {e}")
        return {"gas": {"industrial": {"natural": [], "technological": []}, "utility": []}, "liquid": {"industrial": []}}

equipment_db = load_equipment_db()

# Хранилище сессий пользователей (в продакшене использовать Redis или БД)
user_sessions = {}
user_searches = {}  # Хранение поисков пользователей
questionnaire_counter = 0  # Счетчик для генерации ID опросных листов

# Основные маршруты
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Главная страница приложения - Шаг 1: Выбор категории оборудования"""
    return templates.TemplateResponse(request, "index.html")

@app.get("/measuring-instruments", response_class=HTMLResponse)
async def measuring_instruments_page(request: Request):
    """Страница выбора типа контрольно-измерительных приборов (Шаг 1.1)"""
    return templates.TemplateResponse(request, "measuring_instruments.html")

@app.get("/medium", response_class=HTMLResponse)
async def medium_page(request: Request, equipment_type: Optional[str] = None):
    """Страница выбора среды (Шаг 2)"""
    return templates.TemplateResponse(request, "medium.html", {"equipment_type": equipment_type})

@app.get("/application", response_class=HTMLResponse)
async def application_page(request: Request, equipment_type: Optional[str] = None, medium: Optional[str] = None):
    """Страница выбора сферы применения (Шаг 3)"""
    return templates.TemplateResponse(request, "application.html", {"equipment_type": equipment_type, "medium": medium})

@app.get("/gas-type", response_class=HTMLResponse)
async def gas_type_page(request: Request, medium: Optional[str] = None, application: Optional[str] = None):
    """Страница выбора типа газа (Шаг 3)"""
    return templates.TemplateResponse(request, "gas_type.html", {"medium": medium, "application": application})

@app.get("/params", response_class=HTMLResponse)
async def params_page(request: Request, medium: Optional[str] = None, application: Optional[str] = None, gas_type: Optional[str] = None):
    """Страница ввода параметров (Шаг 4)"""
    return templates.TemplateResponse(request, "params.html", {"medium": medium, "application": application, "gas_type": gas_type})

@app.get("/auth", response_class=HTMLResponse)
async def auth_page(request: Request):
    """Страница авторизации"""
    return templates.TemplateResponse(request, "auth.html")

@app.get("/login", response_class=HTMLResponse)
async def login_redirect(request: Request, session: Optional[str] = None):
    """Обработка перехода из 1С с session_id"""
    logger.info(f"Переход из 1С с session_id: {session}")
    
    if session:
        # Сохраняем session_id в cookies для дальнейшего использования
        response = templates.TemplateResponse(request, "index.html")
        response.set_cookie(key="session_id", value=session, max_age=3600)  # 1 час
        logger.info(f"Session ID {session} сохранен в cookies")
        return response
    else:
        # Если нет session_id, просто перенаправляем на главную
        logger.warning("Переход из 1С без session_id")
        return templates.TemplateResponse(request, "index.html")

@app.get("/test_direct_1c.html", response_class=HTMLResponse)
async def test_direct_1c_page():
    """Страница для тестирования прямого подключения к 1С"""
    file_path = os.path.join(BASE_DIR, "test_direct_1c.html")
    if not os.path.exists(file_path):
        logger.error(f"Файл не найден: {file_path}")
        raise HTTPException(status_code=404, detail=f"Файл test_direct_1c.html не найден")
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Ошибка чтения файла {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка чтения файла: {str(e)}")

@app.get("/test_direct_1c_with_data.html", response_class=HTMLResponse)
async def test_direct_1c_with_data_page():
    """Расширенная страница для тестирования прямого подключения к 1С с отправкой данных"""
    file_path = os.path.join(BASE_DIR, "test_direct_1c_with_data.html")
    if not os.path.exists(file_path):
        logger.error(f"Файл не найден: {file_path}")
        raise HTTPException(status_code=404, detail=f"Файл test_direct_1c_with_data.html не найден")
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Ошибка чтения файла {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка чтения файла: {str(e)}")

@app.get("/results", response_class=HTMLResponse)
async def results_page(request: Request, 
                      medium: Optional[str] = None,
                      application: Optional[str] = None, 
                      gas_type: Optional[str] = None,
                      search_id: Optional[str] = None,
                      flow_min: Optional[str] = None,
                      flow_max: Optional[str] = None,
                      flow_unit: Optional[str] = None,
                      pressure_min: Optional[str] = None,
                      pressure_max: Optional[str] = None,
                      pressure_unit: Optional[str] = None,
                      temperature_min: Optional[str] = None,
                      temperature_max: Optional[str] = None,
                      temperature_unit: Optional[str] = None,
                      ambient_temp_min: Optional[str] = None,
                      ambient_temp_max: Optional[str] = None,
                      accuracy: Optional[str] = None,
                      diameter: Optional[str] = None,
                      density_min: Optional[str] = None,
                      density_max: Optional[str] = None):
    """Страница результатов поиска"""
    
    # Преобразуем gas_type для отображения
    gas_type_display = None
    if gas_type:
        gas_type_map = {
            'natural': 'Природный газ',
            'propane': 'Пропан',
            'air': 'Воздух',
            'steam': 'Пар'
        }
        gas_type_display = gas_type_map.get(gas_type, gas_type)
    
    # Создаем параметры поиска для получения результатов
    search_params = EquipmentParams(
        medium=medium or "gas",
        application=application,
        gas_type=gas_type,
        flow_min=flow_min,
        flow_max=flow_max,
        flow_unit=flow_unit,
        pressure_min=pressure_min,
        pressure_max=pressure_max,
        pressure_unit=pressure_unit,
        temperature_min=temperature_min,
        temperature_max=temperature_max,
        temperature_unit=temperature_unit,
        accuracy=accuracy,
        diameter=diameter
    )
    
    # Выполняем поиск оборудования
    print(f"\n=== RESULTS PAGE DEBUG ===")
    print(f"Search params: {search_params}")
    equipment_results = find_matching_equipment(search_params)
    print(f"Equipment results count: {len(equipment_results)}")
    print(f"Equipment results: {equipment_results}")
    print(f"=== END DEBUG ===")
    
    # Добавляем рекомендуемый диаметр для каждого оборудования
    for equipment in equipment_results:
        equipment['recommended_diameter'] = get_recommended_diameter_for_equipment(equipment, search_params)
    
    # Получаем рекомендуемый диаметр
    recommended_diameter = get_recommended_diameter_for_cfm(search_params)
    
    # Формируем строки диапазонов для отображения
    flow_range = None
    if flow_min or flow_max:
        flow_parts = []
        if flow_min:
            flow_parts.append(f"от {flow_min}")
        if flow_max:
            flow_parts.append(f"до {flow_max}")
        if flow_unit:
            flow_range = f"{' '.join(flow_parts)} {flow_unit}"
        else:
            flow_range = ' '.join(flow_parts)
    
    pressure_range = None
    if pressure_min or pressure_max:
        pressure_parts = []
        if pressure_min:
            pressure_parts.append(f"от {pressure_min}")
        if pressure_max:
            pressure_parts.append(f"до {pressure_max}")
        if pressure_unit:
            pressure_range = f"{' '.join(pressure_parts)} {pressure_unit}"
        else:
            pressure_range = ' '.join(pressure_parts)
    
    temperature_range = None
    if temperature_min or temperature_max:
        temp_parts = []
        if temperature_min:
            temp_parts.append(f"от {temperature_min}")
        if temperature_max:
            temp_parts.append(f"до {temperature_max}")
        if temperature_unit:
            temperature_range = f"{' '.join(temp_parts)} {temperature_unit}"
        else:
            temperature_range = ' '.join(temp_parts)
    
    # Формируем диапазон температуры окружающей среды
    ambient_temp_range = None
    if ambient_temp_min or ambient_temp_max:
        ambient_parts = []
        if ambient_temp_min:
            ambient_parts.append(f"от {ambient_temp_min}")
        if ambient_temp_max:
            ambient_parts.append(f"до {ambient_temp_max}")
        ambient_temp_range = f"{' '.join(ambient_parts)} °C"
    
    template_data = {
        "request": request,
        "medium": medium,
        "application": application,
        "gas_type": gas_type,
        "gas_type_display": gas_type_display,
        "equipment": equipment_results,
        "total": len(equipment_results),
        "flow_range": flow_range,
        "pressure_range": pressure_range,
        "temperature_range": temperature_range,
        "ambient_temp_range": ambient_temp_range,
        "accuracy": accuracy,
        "diameter": diameter,
        "recommended_diameter": recommended_diameter
    }
    print(f"Template data: {template_data}")
    return templates.TemplateResponse(request, "results.html", template_data)

@app.get("/api/search-equipment")
async def search_equipment_api(
                      medium: Optional[str] = None,
                      application: Optional[str] = None, 
                      gas_type: Optional[str] = None,
                      flowMin: Optional[str] = None,
                      flowMax: Optional[str] = None,
                      flow_unit: Optional[str] = None,
                      diameter: Optional[str] = None,
                      pressureMin: Optional[str] = None,
                      pressureMax: Optional[str] = None,
                      tempMediumMin: Optional[str] = None,
                      tempMediumMax: Optional[str] = None,
                      tempAmbientMin: Optional[str] = None,
                      tempAmbientMax: Optional[str] = None,
                      accuracy: Optional[str] = None,
                      densityMin: Optional[str] = None,
                      densityMax: Optional[str] = None,
                      allowedEquipmentIds: Optional[str] = None):
    """API endpoint для поиска оборудования (возвращает JSON)"""
    
    # Создаем параметры поиска
    search_params = EquipmentParams(
        medium=medium or "gas",
        application=application,
        gas_type=gas_type,
        flow_min=flowMin,
        flow_max=flowMax,
        flow_unit=flow_unit or "м³/ч",  # Используем переданное значение или м³/ч по умолчанию
        pressure_min=pressureMin,
        pressure_max=pressureMax,
        pressure_unit="МПа",  # По умолчанию
        temperature_min=tempMediumMin,
        temperature_max=tempMediumMax,
        temperature_unit="°C",  # По умолчанию
        ambient_temp_min=tempAmbientMin,
        ambient_temp_max=tempAmbientMax,
        accuracy=accuracy,
        diameter=diameter,
        density_min=densityMin,
        density_max=densityMax
    )
    
    # Парсим разрешённые ID оборудования (если указаны)
    allowed_ids = None
    if allowedEquipmentIds:
        allowed_ids = [id.strip() for id in allowedEquipmentIds.split(',')]
        print(f"🎯 Фильтрация по разрешённым ID: {allowed_ids}")
    
    # Выполняем поиск
    equipment_results = find_matching_equipment(search_params)
    
    # Фильтруем по разрешённым ID (если указаны)
    if allowed_ids:
        equipment_results = [eq for eq in equipment_results if eq.get('id') in allowed_ids]
        print(f"✅ После фильтрации по ID осталось: {len(equipment_results)} расходомеров")
    
    # Добавляем рекомендуемый диаметр и формируем image_url
    for equipment in equipment_results:
        equipment['recommended_diameter'] = get_recommended_diameter_for_equipment(equipment, search_params)
        # Формируем полный URL для изображения
        if equipment.get('image'):
            equipment['image_url'] = f"/static/{equipment['image']}"
        else:
            equipment['image_url'] = None
    
    return {
        "status": "success",
        "total": len(equipment_results),
        "equipment": equipment_results
    }

@app.get("/api/search-densitometer")
async def search_densitometer_api(
                      densityMin: Optional[str] = None,
                      densityMax: Optional[str] = None,
                      pressureMin: Optional[str] = None,
                      pressureMax: Optional[str] = None,
                      tempMediumMin: Optional[str] = None,
                      tempMediumMax: Optional[str] = None,
                      tempAmbientMin: Optional[str] = None,
                      tempAmbientMax: Optional[str] = None,
                      accuracy: Optional[str] = None,
                      diameter: Optional[str] = None):
    """API endpoint для поиска плотномеров (возвращает JSON)"""
    
    # Получаем список плотномеров из базы
    densitometer_list = equipment_db.get("densitometer", [])
    
    print(f"\n=== ПОИСК ПЛОТНОМЕРОВ ===")
    print(f"Найдено плотномеров в базе: {len(densitometer_list)}")
    print(f"Параметры поиска: плотность={densityMin}-{densityMax}, давление={pressureMin}-{pressureMax}")
    print(f"Параметры поиска: диаметр={diameter}")
    
    # Функция для конвертации строки в число
    def safe_float(value):
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return float(value.replace(',', '.'))
        elif isinstance(value, (int, float)):
            return float(value)
        return None
    
    # Фильтруем по параметрам
    suitable_results = []
    
    for equipment in densitometer_list:
        specs = equipment.get("specs", {})
        is_suitable = True
        
        # Проверка диапазона плотности
        user_density_min = safe_float(densityMin)
        user_density_max = safe_float(densityMax)
        if user_density_min is not None or user_density_max is not None:
            density_range = specs.get("densityRange", "")
            if density_range:
                spec_density_min = _extract_min_value(density_range)
                spec_density_max = _extract_max_value(density_range)
                
                if user_density_min is not None and user_density_min < spec_density_min:
                    print(f"ОТКЛОНЕНО: мин. плотность {user_density_min} < {spec_density_min}")
                    is_suitable = False
                if user_density_max is not None and user_density_max > spec_density_max:
                    print(f"ОТКЛОНЕНО: макс. плотность {user_density_max} > {spec_density_max}")
                    is_suitable = False
        
        # Проверка давления
        user_pressure_min = safe_float(pressureMin)
        user_pressure_max = safe_float(pressureMax)
        if is_suitable and (user_pressure_min is not None or user_pressure_max is not None):
            pressure_range = specs.get("pressureRange", "")
            if pressure_range:
                spec_pressure_min = _extract_min_value(pressure_range)
                spec_pressure_max = _extract_max_value(pressure_range)
                
                if user_pressure_min is not None and user_pressure_min < spec_pressure_min:
                    print(f"ОТКЛОНЕНО: мин. давление {user_pressure_min} < {spec_pressure_min}")
                    is_suitable = False
                if user_pressure_max is not None and user_pressure_max > spec_pressure_max:
                    print(f"ОТКЛОНЕНО: макс. давление {user_pressure_max} > {spec_pressure_max}")
                    is_suitable = False
        
        # Проверка температуры измеряемой среды
        user_temp_min = safe_float(tempMediumMin)
        user_temp_max = safe_float(tempMediumMax)
        if is_suitable and (user_temp_min is not None or user_temp_max is not None):
            temp_range = specs.get("tempRange", "")
            if temp_range:
                spec_temp_min = _extract_min_value(temp_range)
                spec_temp_max = _extract_max_value(temp_range)
                
                if user_temp_min is not None and user_temp_min < spec_temp_min:
                    print(f"ОТКЛОНЕНО: мин. температура среды {user_temp_min} < {spec_temp_min}")
                    is_suitable = False
                if user_temp_max is not None and user_temp_max > spec_temp_max:
                    print(f"ОТКЛОНЕНО: макс. температура среды {user_temp_max} > {spec_temp_max}")
                    is_suitable = False
        
        # Проверка температуры окружающей среды
        user_ambient_min = safe_float(tempAmbientMin)
        user_ambient_max = safe_float(tempAmbientMax)
        if is_suitable and (user_ambient_min is not None or user_ambient_max is not None):
            ambient_range = specs.get("ambientTempRange", "")
            if ambient_range:
                spec_ambient_min = _extract_min_value(ambient_range)
                spec_ambient_max = _extract_max_value(ambient_range)
                
                if user_ambient_min is not None and user_ambient_min < spec_ambient_min:
                    print(f"ОТКЛОНЕНО: мин. температура окр. среды {user_ambient_min} < {spec_ambient_min}")
                    is_suitable = False
                if user_ambient_max is not None and user_ambient_max > spec_ambient_max:
                    print(f"ОТКЛОНЕНО: макс. температура окр. среды {user_ambient_max} > {spec_ambient_max}")
                    is_suitable = False
        
        # Проверка точности
        user_accuracy = safe_float(accuracy)
        if is_suitable and user_accuracy is not None:
            accuracy_range = specs.get("accuracy", "")
            if accuracy_range:
                spec_accuracy_min = _extract_min_value(accuracy_range)
                if user_accuracy < spec_accuracy_min:
                    print(f"ОТКЛОНЕНО: точность {user_accuracy} < {spec_accuracy_min}")
                    is_suitable = False
        
        # Проверка диаметра
        user_diameter = safe_float(diameter)
        if is_suitable and user_diameter is not None:
            diameter_range = specs.get("diameterRange", "")
            if diameter_range:
                spec_diameter_min = _extract_min_value(diameter_range)
                spec_diameter_max = _extract_max_value(diameter_range)
                
                if user_diameter < spec_diameter_min or user_diameter > spec_diameter_max:
                    print(f"ОТКЛОНЕНО: диаметр {user_diameter} не в диапазоне {spec_diameter_min}-{spec_diameter_max}")
                    is_suitable = False
        
        if is_suitable:
            equipment_copy = equipment.copy()
            # Формируем полный URL для изображения
            if equipment_copy.get('image'):
                equipment_copy['image_url'] = f"/static/{equipment_copy['image']}"
            else:
                equipment_copy['image_url'] = None
            suitable_results.append(equipment_copy)
            print(f"✓ Подходит: {equipment.get('name')}")
    
    print(f"Итого найдено: {len(suitable_results)}")
    
    return {
        "status": "success",
        "total": len(suitable_results),
        "equipment": suitable_results
    }

@app.get("/api/test-1c-connection")
async def test_1c_connection():
    """Тестирование подключения к серверу 1С с улучшенной диагностикой для хостинга"""
    import aiohttp
    import json
    import ssl
    import logging
    
    # Настройка логирования
    logger = logging.getLogger(__name__)
    
    # Улучшенная конфигурация подключения к 1С для хостинга
    config_1c = {
        'base_url': 'https://web.turbo-don.ru/web1C/hs',
        'endpoint': 'Options',
        'timeout': 60,  # Увеличиваем таймаут для хостинга
        'connect_timeout': 30,
        'auth_token': ONE_C_AUTH_TOKEN
    }
    
    # Рабочие заголовки (как в успешном тесте)
    headers = {
        'Authorization': config_1c['auth_token'],
        'User-Agent': 'PostmanRuntime/7.32.3',  # Используем рабочий User-Agent
        'Accept': 'application/json, text/plain, */*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache'  # Добавляем заголовок из успешного теста
    }
    
    # Рабочий SSL контекст (как в успешном тесте)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    # Устанавливаем современные шифры
    ssl_context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS')
    
    try:
        # Улучшенные настройки таймаута (как в успешном тесте)
        timeout = aiohttp.ClientTimeout(
            total=30,  # Общий таймаут как в успешном тесте
            connect=10,  # Таймаут подключения как в успешном тесте
            sock_read=30  # Таймаут чтения как в успешном тесте
        )
        
        # Создаем коннектор с SSL настройками
        connector = aiohttp.TCPConnector(
            ssl=ssl_context,
            limit=10,
            limit_per_host=5,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers
        ) as session:
            # Формируем полный URL
            if config_1c['endpoint']:
                full_url = f"{config_1c['base_url']}/{config_1c['endpoint']}"
            else:
                full_url = config_1c['base_url']
            
            logger.info(f"🔍 Тестируем подключение к 1С: {full_url}")
            
            # Отправляем GET запрос с улучшенной обработкой
            async with session.get(url=full_url) as response:
                response_text = await response.text()
                
                logger.info(f"📨 Получен ответ от 1С: статус {response.status}")
                
                return {
                    "status": "success" if response.status == 200 else "error",
                    "message": "Сервер 1С доступен" if response.status == 200 else f"Ошибка сервера 1С: {response.status}",
                    "url": full_url,
                    "http_status": response.status,
                    "response_text": response_text[:500],  # Ограничиваем размер ответа
                    "headers": dict(response.headers),
                    "connection_info": {
                        "ssl_enabled": True,
                        "timeout_settings": {
                            "total": config_1c['timeout'],
                            "connect": config_1c['connect_timeout']
                        }
                    }
                }
                    
    except aiohttp.ClientConnectorError as e:
        logger.error(f"🔌 Ошибка подключения к 1С: {e}")
        return {
            "status": "error",
            "message": f"Не удается подключиться к серверу 1С: {str(e)}",
            "url": f"{config_1c['base_url']}/{config_1c['endpoint']}",
            "error_type": "connection_error",
            "suggestions": [
                "Проверьте, разрешены ли исходящие HTTPS-соединения на хостинге",
                "Убедитесь, что хостинг не блокирует домен web.turbo-don.ru",
                "Проверьте настройки файрволла хостинга",
                "Обратитесь к службе поддержки хостинга"
            ]
        }
    except aiohttp.ServerTimeoutError as e:
        logger.error(f"⏰ Таймаут при подключении к 1С: {e}")
        return {
            "status": "error",
            "message": f"Превышено время ожидания ответа от сервера 1С: {str(e)}",
            "url": f"{config_1c['base_url']}/{config_1c['endpoint']}",
            "error_type": "timeout_error",
            "suggestions": [
                "Увеличьте таймаут в настройках",
                "Проверьте скорость соединения хостинга",
                "Обратитесь к администратору сервера 1С"
            ]
        }
    except ssl.SSLError as e:
        logger.error(f"🔒 Ошибка SSL при подключении к 1С: {e}")
        return {
            "status": "error",
            "message": f"Ошибка SSL при подключении к серверу 1С: {str(e)}",
            "url": f"{config_1c['base_url']}/{config_1c['endpoint']}",
            "error_type": "ssl_error",
            "suggestions": [
                "Проверьте SSL-сертификат сервера 1С",
                "Обновите корневые сертификаты на хостинге",
                "Обратитесь к администратору хостинга"
            ]
        }
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при подключении к 1С: {e}")
        return {
            "status": "error",
            "message": f"Неожиданная ошибка при подключении к 1С: {str(e)}",
            "url": f"{config_1c['base_url']}/{config_1c['endpoint']}",
            "error_type": "unknown_error",
            "error": str(e)
        }

# Добавляем endpoint для диагностики хостинга
@app.get("/api/health")
async def health_check():
    """Проверка работоспособности сервера на хостинге"""
    try:
        import httpx
        import ssl
        from httpx._config import create_ssl_context
        
        # Авторизация для 1С
        auth_token = ONE_C_AUTH_TOKEN
        
        # Заголовки как в успешном Postman тесте
        headers = {
            'Authorization': auth_token,
            'User-Agent': 'PostmanRuntime/7.32.3',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache'
        }
        
        # Создаем SSL контекст как в успешном тесте
        ssl_context = create_ssl_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Настройки SSL как в современных браузерах/Postman
        try:
            ssl_context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS')
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
        except AttributeError:
            # Для старых версий Python
            pass
        
        # Проверяем доступность 1С сервера с улучшенными настройками
        timeout_config = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
        
        async with httpx.AsyncClient(
            verify=False, 
            timeout=timeout_config,
            headers=headers,
            follow_redirects=True
        ) as client:
            response = await client.get("https://web.turbo-don.ru/web1C/hs/Options")
            
        return {
            "status": "ok",
            "server": "running",
            "dependencies": {
                "httpx": "available",
                "ssl": "available"
            },
            "1c_server": {
                "reachable": True,
                "status_code": response.status_code,
                "authenticated": response.status_code == 200,
                "response_time": f"{response.elapsed.total_seconds():.2f}s",
                "server_info": response.headers.get("Server", "unknown")
            }
        }
    except ImportError as e:
        return {
            "status": "error",
            "error": f"Missing dependency: {str(e)}",
            "dependencies": {
                "httpx": "missing",
                "ssl": "unknown"
            }
        }
    except Exception as e:
        return {
            "status": "error", 
            "error": str(e),
            "dependencies": {
                "httpx": "available",
                "ssl": "available"
            },
            "1c_server": {
                "reachable": False,
                "error": str(e)
            }
        }


# Прайс бытовых счётчиков газа «Гранд» (синхронизировать с templates/index.html → grandPriceData)
GRAND_GAS_METER_PRICES_ITEMS: List[Dict[str, Any]] = [
    {"name": 'Счётчик газа Гранд 1.6 1/2" РОССИЯ', "price": 1800},
    {"name": 'Счётчик газа Гранд 1.6 ТК 1/2" РОССИЯ', "price": 2000},
    {"name": 'Счётчик газа Гранд 3.2 1/2" РОССИЯ', "price": 1900},
    {"name": 'Счётчик газа Гранд 3.2 ТК 1/2" РОССИЯ', "price": 2100},
    {"name": 'Счётчик газа Гранд 4 3/4" РОССИЯ', "price": 4100},
    {"name": 'Счётчик газа Гранд 4 1" РОССИЯ', "price": 4400},
    {"name": 'Счётчик газа Гранд 4 1 1/4" РОССИЯ', "price": 4500},
    {"name": 'Счётчик газа Гранд 4 3/4"×154 мм РОССИЯ', "price": 3000},
    {"name": 'Счётчик газа Гранд 4 Б/К 3/4" РОССИЯ', "price": 2300},
    {"name": 'Счётчик газа Гранд 4 ТК 3/4" РОССИЯ', "price": 4200},
    {"name": 'Счётчик газа Гранд 4 ТК 1" РОССИЯ', "price": 4500},
    {"name": 'Счётчик газа Гранд 4 ТК 1 1/4" РОССИЯ', "price": 4600},
    {"name": 'Счётчик газа Гранд 4 ТК 3/4"×154 мм РОССИЯ', "price": 3000},
    {"name": 'Счётчик газа Гранд 4 Б/К ТК 3/4" РОССИЯ', "price": 2400},
    {"name": 'Счётчик газа Гранд 6 Б/К 3/4" РОССИЯ', "price": 2300},
    {"name": 'Счётчик газа Гранд 6 ТК 3/4" РОССИЯ', "price": 2700},
    {"name": 'Счётчик газа Гранд 6 ТК 1" РОССИЯ', "price": 4600},
    {"name": 'Счётчик газа Гранд 6 ТК 1 1/4" РОССИЯ', "price": 4600},
    {"name": 'Счётчик газа Гранд 6 ТК 3/4" РОССИЯ', "price": 4300},
    {"name": 'Счётчик газа Гранд 6 ТК 3/4"×154 мм РОССИЯ', "price": 3600},
    {"name": 'Счётчик газа Гранд 10 ТК 1" РОССИЯ', "price": 4500},
    {"name": 'Счётчик газа Гранд 10 ТК 1 1/4" РОССИЯ', "price": 4600},
    {"name": 'Счётчик газа Гранд 16 ТК 2" РОССИЯ', "price": 7100},
    {"name": 'Счётчик газа Гранд 25 ТК 2" РОССИЯ', "price": 8000},
    {"name": 'Счётчик газа Гранд 4 ТК М 3/4" РОССИЯ', "price": 5500},
    {"name": 'Счётчик газа Гранд 4 ТК М 1" РОССИЯ', "price": 5500},
    {"name": 'Счётчик газа Гранд 4 ТК М 1 1/4" РОССИЯ', "price": 5300},
    {"name": 'Счётчик газа Гранд 4 ТК М 3/4"×154 мм РОССИЯ', "price": 5400},
    {"name": 'Счётчик газа Гранд 6 ТК М 3/4" РОССИЯ', "price": 5700},
    {"name": 'Счётчик газа Гранд 6 ТК М 1" РОССИЯ', "price": 6100},
    {"name": 'Счётчик газа Гранд 6 ТК М 1 1/4" РОССИЯ', "price": 6100},
    {"name": 'Счётчик газа Гранд 6 ТК М 3/4"×154 мм РОССИЯ', "price": 6000},
    {"name": 'Счётчик газа Гранд 10 ТК М 1" РОССИЯ', "price": 6400},
    {"name": 'Счётчик газа Гранд 10 ТК М 1 1/4" РОССИЯ', "price": 6400},
    {"name": 'Счётчик газа Гранд 16 ТК М 2" РОССИЯ', "price": 5500},
    {"name": 'Счётчик газа Гранд 25 ТК М 2" РОССИЯ', "price": 8500},
]


@app.get("/api/prices/grand-gas-meters", tags=["api"])
@app.get("/api/prices/grand-gas-meters/", include_in_schema=False)
async def api_grand_gas_meter_prices():
    """
    Прайс-лист счётчиков газа СГ Гранд: наименование и цена (₽, без НДС), как на сайте.
    """
    return {
        "title": "Прайс-лист на СГ Гранд",
        "subtitle": "Стоимость в рублях без НДС (0%)",
        "currency": "RUB",
        "count": len(GRAND_GAS_METER_PRICES_ITEMS),
        "items": GRAND_GAS_METER_PRICES_ITEMS,
    }


@app.get("/api/estimate-price", tags=["api"])
async def api_estimate_price_discovery():
    """
    Если открыть этот URL в браузере — ответ должен быть 200 JSON (маршрут существует).
    Расчёт выполняется только методом POST.
    """
    return {
        "status": "ok",
        "message": "Маршрут найден. Для расчёта отправьте POST с телом JSON (см. /docs или схему EstimatePriceRequest).",
        "use_method": "POST",
        "content_type": "application/json",
        "paths_post": ["/api/estimate-price", "/api/estimate_price"],
        "example_body": {
            "equipment": {"id": "ufg2"},
            "dn": 50,
            "pressure_max_mpa": 1.6,
            "accuracy_percent": 1.0,
        },
    }


@app.post("/api/estimate-price", response_model=EstimatePriceResponse, tags=["api"])
@app.post("/api/estimate_price", response_model=EstimatePriceResponse, tags=["api"])
async def api_estimate_price(payload: EstimatePriceRequest):
    """Примерная цена прибора (таблицы как в templates/index.html). Без авторизации."""
    # Уведомление менеджеру — только через POST /api/send-price-inquiry после верификации.
    return estimate_from_request(payload)


@app.get("/api/tkp-accessories", tags=["api"])
async def api_tkp_accessories_discovery():
    """Подсказка по POST /api/tkp-accessories."""
    return tkp_discovery_message()


@app.post("/api/tkp-accessories", response_model=TkpAccessoriesResponse, tags=["api"])
@app.post("/api/tkp_accessories", response_model=TkpAccessoriesResponse, tags=["api"])
async def api_tkp_accessories(body: TkpAccessoriesRequest):
    """Дополнительные комплектующие для конфигуратора ТКП (аналог блока модалки на сайте)."""
    return tkp_accessories_from_request(body)


@app.get("/api/tkp-pdf", tags=["api"])
async def api_tkp_pdf_hint():
    """Подсказка по POST /api/tkp-pdf (генерация PDF для скачивания)."""
    return tkp_pdf_discovery()


@app.post("/api/tkp-pdf", tags=["api"])
@app.post("/api/tkp_pdf", tags=["api"])
async def api_tkp_pdf(body: TkpPdfRequest):
    """
    Формирует PDF (черновое ТКП) по данным карточки и списку комплектующих.
    Ответ: двоичный PDF, скачивание через Content-Disposition.
    """
    try:
        pdf_bytes = build_tkp_pdf_bytes(body)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    fd, tmp_path = tempfile.mkstemp(prefix="tkp_", suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as wf:
            wf.write(pdf_bytes)
    except Exception:
        _unlink_quiet(tmp_path)
        raise

    fname = tkp_pdf_attachment_filename(body)
    safe_bn = Path(str(fname).replace("\\", "/")).name.strip() or "tkp.pdf"
    if len(safe_bn) > 200:
        stem = Path(safe_bn).stem[:180]
        safe_bn = (stem + ".pdf")[:200]

    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename=safe_bn,
        background=BackgroundTask(_unlink_quiet, tmp_path),
    )


@app.post("/api/proxy-to-1c")
@app.get("/api/proxy-to-1c")
async def proxy_to_1c(request: Request):
    """Прокси для отправки данных в 1С через наш сервер с улучшенной обработкой для хостинга"""
    import aiohttp
    import tempfile
    import ssl
    import logging
    
    # Настройка логирования
    logger = logging.getLogger(__name__)
    
    # Улучшенная конфигурация подключения к 1С для хостинга
    config_1c = {
        'base_url': 'https://web.turbo-don.ru/web1C/hs',  # Прямое подключение к новому серверу
        'endpoint': 'Options',  # Endpoint для 1С
        'timeout': 60,  # Увеличиваем таймаут для хостинга
        'connect_timeout': 30,
        'auth_token': ONE_C_AUTH_TOKEN
    }
    
    # Рабочие заголовки (точно как в успешном тесте test_postman_exact.py)
    headers = {
        'Authorization': config_1c['auth_token'],
        'User-Agent': 'PostmanRuntime/7.32.3',  # ✅ Рабочий User-Agent из успешного теста
        'Accept': '*/*',  # ✅ Как в успешном тесте
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',  # ✅ Добавляем из успешного теста
        'Postman-Token': os.getenv('POSTMAN_TOKEN', '')
    }
    
    # Рабочий SSL контекст (точно как в успешном тесте test_postman_exact.py)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    # ✅ Настройки SSL как в современных браузерах/Postman (из успешного теста)
    ssl_context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS')
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
    ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
    
    try:
        # Детальное логирование для диагностики хостинга
        logger.info(f"🔄 Прокси: начало обработки запроса {request.method}")
        
        # Получаем данные из запроса
        if request.method == "GET":
            # Для GET запросов получаем параметры из query string
            query_params = dict(request.query_params)
            request_data = {
                'method': 'GET',
                'params': query_params
            }
            logger.info(f"📥 GET запрос с параметрами: {query_params}")
        else:
            # Для POST запросов получаем данные из JSON body
            try:
                request_data = await request.json()
                logger.info(f"📥 POST запрос с данными: {request_data}")
            except Exception as json_error:
                logger.error(f"❌ Ошибка парсинга JSON: {json_error}")
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Ошибка парсинга JSON: {str(json_error)}"}
                )
        
        method = request_data.get('method', 'GET')  # Возвращаем GET метод
        params = request_data.get('params', {})
        
        logger.info(f"🔄 Прокси: получен {method} запрос с параметрами: {params}")
        
        # Извлекаем JSON данные
        original_json_data = params.get('data', '{}')
        action = params.get('action', 'createnewOL')
        
        # Преобразуем данные в новый формат search_characteristics
        try:
            original_data = json.loads(original_json_data)
            logger.info(f"🔍 Структура исходных данных: {list(original_data.keys())}")
            
            # Извлекаем параметры поиска из оригинальных данных
            # Данные могут быть в data.search_parameters или в корне
            data_section = original_data.get('data', {})
            search_params = data_section.get('search_parameters', original_data.get('search_parameters', {}))
            
            # Извлекаем информацию об оборудовании
            equipment_data = data_section.get('equipment', original_data.get('equipment', {}))
            
            # Получаем ID и название оборудования
            equipment_id = equipment_data.get('id', '')
            equipment_name = equipment_data.get('name', '')
            
            # Получаем логин пользователя
            user_login = data_section.get('user_login', original_data.get('user_login', ''))
            
            logger.info(f"🎯 Найдено оборудование: ID={equipment_id}, Name={equipment_name}")
            logger.info(f"👤 Логин пользователя: {user_login}")
            logger.info(f"📋 Параметры поиска: {search_params}")
            logger.info(f"🔍 Данные секции data: {list(data_section.keys()) if data_section else 'Нет секции data'}")
            
            # Функция для безопасного преобразования в число
            def safe_number(value, default="0"):
                """Безопасно преобразует значение в строку числа"""
                if not value or value == '':
                    return default
                # Убираем все нечисловые символы кроме точки и минуса
                import re
                cleaned = re.sub(r'[^\d.-]', '', str(value))
                if not cleaned or cleaned in ['-', '.', '-.']:
                    return default
                return cleaned
            
            # Определяем тип оборудования
            equipment_type = data_section.get('equipment_type', original_data.get('equipment_type', 'flowmeter'))
            logger.info(f"📦 Тип оборудования: {equipment_type}")
            
            # Формируем новую структуру данных в зависимости от типа оборудования
            if equipment_type == 'densitometer':
                # Параметры для плотномера
                new_data = {
                    "search_characteristics": {
                        "parameters": {
                            "pressure_min": safe_number(search_params.get('pressure_min', ''), "0.1"),
                            "pressure_max": safe_number(search_params.get('pressure_max', ''), "32"),
                            "temperature_min": safe_number(search_params.get('temperature_min', ''), "-40"),
                            "temperature_max": safe_number(search_params.get('temperature_max', ''), "70"),
                            "ambient_temp_min": safe_number(search_params.get('ambient_temp_min', ''), "-50"),
                            "ambient_temp_max": safe_number(search_params.get('ambient_temp_max', ''), "80"),
                            "density_min": safe_number(search_params.get('density_min', ''), "0.14"),
                            "density_max": safe_number(search_params.get('density_max', ''), "350"),
                            "accuracy": safe_number(search_params.get('accuracy', ''), "1"),
                            "diameter": safe_number(search_params.get('diameter', ''), "")
                        },
                        "id": equipment_id,
                        "name": equipment_name,
                        "user_login": user_login,
                        "equipment_type": "densitometer"
                    }
                }
            else:
                # Параметры для расходомера (по умолчанию)
                new_data = {
                    "search_characteristics": {
                        "parameters": {
                            "pressure_min": safe_number(search_params.get('pressure_min', ''), "0"),
                            "pressure_max": safe_number(search_params.get('pressure_max', ''), "16"),
                            "temperature_min": safe_number(search_params.get('temperature_min', ''), "-40"),
                            "temperature_max": safe_number(search_params.get('temperature_max', ''), "80"),
                            "ambient_temp_min": safe_number(search_params.get('ambient_temp_min', ''), "-40"),
                            "ambient_temp_max": safe_number(search_params.get('ambient_temp_max', ''), "70"),
                            "flow_min": safe_number(search_params.get('flow_min', ''), "10"),
                            "flow_max": safe_number(search_params.get('flow_max', ''), "1000"),
                            "accuracy": safe_number(search_params.get('accuracy', ''), "1"),
                            "diameter": safe_number(search_params.get('diameter', ''), "100"),
                            "flow_unit": search_params.get('flow_unit', 'м³/ч раб.у.'),
                            "gas_conditions": search_params.get('gas_conditions', 'м³/ч раб.у.')
                        },
                        "id": equipment_id,
                        "name": equipment_name,
                        "user_login": user_login,
                        "equipment_type": "flowmeter"
                    }
                }
                
                # Добавляем плотность для жидкостей (если указана)
                density_min = search_params.get('density_min', '')
                density_max = search_params.get('density_max', '')
                if density_min:
                    new_data["search_characteristics"]["parameters"]["density_min"] = density_min
                if density_max:
                    new_data["search_characteristics"]["parameters"]["density_max"] = density_max
            
            # Добавляем specialTag если есть
            logger.info(f"🔍 Все ключи original_data: {list(original_data.keys())}")
            logger.info(f"🔍 Полный original_data: {original_data}")
            special_tag = original_data.get('specialTag')
            logger.info(f"🔍 Найден specialTag: {special_tag}")
            if special_tag:
                new_data["search_characteristics"]["specialTag"] = special_tag
                logger.info(f"🏷️ Добавлен specialTag в new_data: {special_tag}")
            else:
                logger.info(f"⚠️ specialTag НЕ найден в данных")
            
            json_data = json.dumps(new_data, ensure_ascii=False)
            logger.info(f"🔄 Преобразованные данные для 1С: {json_data}")
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"⚠️ Ошибка преобразования данных: {e}")
            logger.warning(f"📦 Исходные данные: {original_json_data}")
            json_data = original_json_data  # Используем исходные данные в случае ошибки
        
        # Формируем полный URL
        if config_1c['endpoint']:
            full_url = f"{config_1c['base_url']}/{config_1c['endpoint']}"
        else:
            full_url = config_1c['base_url']
        logger.info(f"🎯 Прокси: отправляем запрос к 1С: {full_url}")
        
        # ✅ Рабочие настройки таймаута (как в успешном тесте test_postman_exact.py)
        timeout = aiohttp.ClientTimeout(
            total=30,  # ✅ Как в успешном тесте (10, 30)
            connect=10,  # ✅ Как в успешном тесте
            sock_read=30  # ✅ Как в успешном тесте
        )
        
        # Создаем коннектор с SSL настройками
        connector = aiohttp.TCPConnector(
            ssl=ssl_context,
            limit=10,
            limit_per_host=5,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        logger.info(f"🔗 Создание HTTP сессии с таймаутом {config_1c['timeout']}с")
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers
        ) as session:
            logger.info(f"📤 Прокси: отправляем GET запрос с JSON в параметрах...")
            logger.info(f"📋 Параметры запроса: data={json_data[:100]}...")
            
            try:
                # Используем urllib.parse.quote_plus для URL-кодирования
                # quote_plus использует + для пробелов (как требует 1С)
                from urllib.parse import quote_plus
                
                # Кодируем data с плюсиками (пробелы → +)
                encoded_action = quote_plus(action)
                encoded_data = quote_plus(json_data)
                
                # user_login кодируем с плюсиками, но кавычки оставляем как есть
                encoded_user_login = quote_plus(user_login, safe='"')
                
                # Формируем URL вручную
                url_with_params = f"{full_url}?action={encoded_action}&user_login={encoded_user_login}&data={encoded_data}"
                
                logger.info(f"📋 Параметры запроса к 1С: action={action}, user_login={user_login}")
                logger.info(f"📋 URL: {url_with_params[:300]}...")
                
                async with session.get(url=url_with_params) as response:
                        response_text = await response.text()
                        logger.info(f"📨 Прокси: получен ответ от 1С - статус: {response.status}")
                        logger.info(f"📄 Прокси: текст ответа: {response_text[:200]}...")
                        
                        result = {
                            "status": "success",
                            "response_status": response.status,
                            "response_text": response_text
                        }
                        
                        # Проверяем, есть ли ошибка в ответе 1С
                        if response.status >= 400:
                            result["status"] = "error"
                            result["message"] = f"Сервер 1С вернул ошибку {response.status}"
                        
                        return result
            except Exception as request_error:
                logger.error(f"❌ Ошибка при выполнении HTTP запроса: {request_error}")
                logger.error(f"🔍 Тип ошибки: {type(request_error).__name__}")
                raise request_error
        
    except aiohttp.ClientConnectorError as e:
        logger.error(f"🔌 Ошибка подключения к 1С: {e}")
        logger.error(f"🔍 Детали ошибки подключения: {type(e).__name__}")
        return {
            "status": "error",
            "message": f"Не удается подключиться к серверу 1С: {str(e)}",
            "error_type": "connection_error",
            "error_details": str(e),
            "suggestions": [
                "Проверьте, разрешены ли исходящие HTTPS-соединения на хостинге",
                "Убедитесь, что хостинг не блокирует домен web.turbo-don.ru",
                "Проверьте настройки файрволла хостинга",
                "Обратитесь к службе поддержки хостинга"
            ]
        }
    except aiohttp.ServerTimeoutError as e:
        logger.error(f"⏰ Таймаут при подключении к 1С: {e}")
        return {
            "status": "error",
            "message": f"Превышено время ожидания ответа от сервера 1С: {str(e)}",
            "error_type": "timeout_error",
            "error_details": str(e),
            "suggestions": [
                "Увеличьте таймаут в настройках",
                "Проверьте скорость соединения хостинга",
                "Обратитесь к администратору сервера 1С"
            ]
        }
    except ssl.SSLError as e:
        logger.error(f"🔒 Ошибка SSL при подключении к 1С: {e}")
        return {
            "status": "error",
            "message": f"Ошибка SSL при подключении к серверу 1С: {str(e)}",
            "error_type": "ssl_error",
            "error_details": str(e),
            "suggestions": [
                "Проверьте SSL-сертификат сервера 1С",
                "Обновите корневые сертификаты на хостинге",
                "Обратитесь к администратору хостинга"
            ]
        }
    except ImportError as e:
        logger.error(f"📦 Ошибка импорта модуля: {e}")
        return {
            "status": "error",
            "message": f"Отсутствует необходимый модуль: {str(e)}",
            "error_type": "import_error",
            "error_details": str(e),
            "suggestions": [
                "Установите недостающие зависимости: pip install aiohttp",
                "Проверьте requirements.txt",
                "Обратитесь к администратору хостинга"
            ]
        }
    except asyncio.TimeoutError:
        error_msg = "Таймаут при подключении к серверу 1С"
        logger.error(f"⏰ Прокси: {error_msg}")
        return {
            "status": "error",
            "message": error_msg,
            "error_type": "timeout_error"
        }
    except Exception as e:
        error_msg = f"Ошибка отправки данных в 1С: {str(e)}"
        logger.error(f"❌ Прокси: {error_msg}")
        logger.error(f"🔍 Тип неожиданной ошибки: {type(e).__name__}")
        logger.error(f"📋 Полная информация об ошибке: {repr(e)}")
        return {
            "status": "error",
            "message": error_msg,
            "error_type": "unknown_error"
        }

def find_matching_equipment(params: EquipmentParams) -> List[Dict[str, Any]]:
    """Функция поиска подходящего оборудования"""
    suitable_equipment, _ = find_equipment_with_unsuitable(params)
    return suitable_equipment

def find_equipment_with_unsuitable(params: EquipmentParams) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Функция поиска оборудования с возвратом подходящего и неподходящего оборудования с причинами отсеивания"""
    suitable_results = []
    unsuitable_results = []
    
    # Конвертация ст.м³/ч в м³/ч (рабочие условия) если необходимо
    if params.flow_unit == "ст.м³/ч":
        def safe_float(value):
            if value is None or value == "":
                return None
            if isinstance(value, str):
                return float(value.replace(',', '.'))
            elif isinstance(value, (int, float)):
                return float(value)
            return None
        
        # Стандартные условия: +20°C (293.15 K), 101.325 кПа
        P_st = 101.325  # кПа
        T_st = 293.15   # K (+20°C)
        
        # Получаем рабочее давление (среднее из диапазона) в МПа, конвертируем в кПа
        pressure_min_val = safe_float(params.pressure_min) or 0.1  # По умолчанию 0.1 МПа
        pressure_max_val = safe_float(params.pressure_max) or pressure_min_val
        P_work = ((pressure_min_val + pressure_max_val) / 2) * 1000  # МПа → кПа
        
        # Получаем рабочую температуру (среднее из диапазона) в °C, конвертируем в K
        temp_min_val = safe_float(params.temperature_min) or 20  # По умолчанию +20°C
        temp_max_val = safe_float(params.temperature_max) or temp_min_val
        T_work = ((temp_min_val + temp_max_val) / 2) + 273.15  # °C → K
        
        # Формула: Q_раб = Q_ст × (P_ст / P_раб) × (T_раб / T_ст)
        conversion_factor = (P_st / P_work) * (T_work / T_st)
        
        print(f"Конвертация ст.м³/ч → м³/ч: P_раб={P_work:.1f} кПа, T_раб={T_work-273.15:.1f}°C, коэф.={conversion_factor:.4f}")
        
        flow_min_converted = None
        flow_max_converted = None
        
        if params.flow_min:
            flow_min_val = safe_float(params.flow_min)
            if flow_min_val is not None:
                flow_min_converted = str(round(flow_min_val * conversion_factor, 4))
        
        if params.flow_max:
            flow_max_val = safe_float(params.flow_max)
            if flow_max_val is not None:
                flow_max_converted = str(round(flow_max_val * conversion_factor, 4))
        
        # Создаем новый объект params с конвертированными значениями
        params = EquipmentParams(
            medium=params.medium,
            application=params.application,
            gas_type=params.gas_type,
            flow_min=flow_min_converted,
            flow_max=flow_max_converted,
            flow_unit="м³/ч",  # Меняем единицу на м³/ч (рабочие условия)
            flow_conditions=params.flow_conditions,
            pressure_min=params.pressure_min,
            pressure_max=params.pressure_max,
            pressure_unit=params.pressure_unit,
            temperature_min=params.temperature_min,
            temperature_max=params.temperature_max,
            temperature_unit=params.temperature_unit,
            ambient_temp_min=params.ambient_temp_min,
            ambient_temp_max=params.ambient_temp_max,
            ambient_temperature_min=params.ambient_temperature_min,
            ambient_temperature_max=params.ambient_temperature_max,
            accuracy=params.accuracy,
            diameter=params.diameter,
            density_min=params.density_min,
            density_max=params.density_max,
            gas_conditions=params.gas_conditions,
            user_id=params.user_id
        )
        print(f"Конвертация ст.м³/ч в м³/ч: {params.flow_min}-{params.flow_max} м³/ч")
    
    # Отладочная информация
    print(f"\n=== ПОИСК ОБОРУДОВАНИЯ ===")
    print(f"Параметры поиска: medium={params.medium}, application={params.application}, gas_type={params.gas_type}")
    print(f"Расход: {params.flow_min}-{params.flow_max} {params.flow_unit}")
    print(f"Давление: {params.pressure_min}-{params.pressure_max} {params.pressure_unit}")
    print(f"Температура: {params.temperature_min}-{params.temperature_max} {params.temperature_unit}")
    print(f"Точность: {params.accuracy}")
    
    # Определяем путь к данным в зависимости от параметров (упрощённая структура)
    if params.medium == "gas":
        equipment_list = equipment_db.get("gas", [])
    else:  # liquid
        equipment_list = equipment_db.get("liquid", [])
    
    print(f"Найдено оборудования в базе: {len(equipment_list)}")
    
    # Фильтрация по параметрам
    for i, equipment in enumerate(equipment_list):
        print(f"\nПроверяем оборудование {i+1}: {equipment.get('name', 'Без названия')}")
        if is_equipment_suitable(equipment, params):
            suitable_results.append(equipment)
            print(f"✓ Подходит!")
        else:
            # Получаем причины отсеивания
            rejection_reasons = get_equipment_rejection_reasons(equipment, params)
            equipment_with_reasons = equipment.copy()
            equipment_with_reasons['rejection_reasons'] = rejection_reasons
            unsuitable_results.append(equipment_with_reasons)
            print(f"✗ Не подходит: {', '.join(rejection_reasons)}")
    
    print(f"\nИтого найдено подходящего оборудования: {len(suitable_results)}")
    print(f"Итого найдено неподходящего оборудования: {len(unsuitable_results)}")
    return suitable_results, unsuitable_results

def is_equipment_suitable(equipment: Dict[str, Any], params: EquipmentParams) -> bool:
    """Проверка соответствия оборудования заданным параметрам"""
    specs = equipment.get("specs", {})
    equipment_name = equipment.get("name", "Unknown")
    print(f"\n--- Проверка оборудования: {equipment_name} ---")
    
    # Конвертируем строковые параметры в числа
    def safe_float(value):
        if value is None or value == "":
            return None
        if isinstance(value, str) and _is_valid_number(value):
            return float(value.replace(',', '.'))
        elif isinstance(value, (int, float)):
            return float(value)
        return None
    
    # Проверка давления
    pressure_min = safe_float(params.pressure_min)
    pressure_max = safe_float(params.pressure_max)
    if pressure_min is not None or pressure_max is not None:
        # Конвертация давления из бар в МПа, если необходимо
        if params.pressure_unit == "бар":
            if pressure_min is not None:
                pressure_min = pressure_min * 0.1  # 1 бар = 0.1 МПа
            if pressure_max is not None:
                pressure_max = pressure_max * 0.1
            print(f"Конвертация давления из бар в МПа: {params.pressure_min}-{params.pressure_max} бар -> {pressure_min}-{pressure_max} МПа")
        
        pressure_range = specs.get("pressureRange", "")
        print(f"Проверка давления: требуется {pressure_min}-{pressure_max} МПа, спецификация: {pressure_range}")
        if pressure_range:
            spec_pressure_min = _extract_min_value(pressure_range)
            spec_pressure_max = _extract_max_value(pressure_range)
            
            if pressure_min is not None and pressure_min < spec_pressure_min:
                print(f"ОТКЛОНЕНО: минимальное давление {pressure_min} < {spec_pressure_min}")
                return False
            if pressure_max is not None and pressure_max > spec_pressure_max:
                print(f"ОТКЛОНЕНО: максимальное давление {pressure_max} > {spec_pressure_max}")
                return False
    
    # Проверка температуры среды
    temperature_min = safe_float(params.temperature_min)
    temperature_max = safe_float(params.temperature_max)
    if temperature_min is not None or temperature_max is not None:
        temp_range = specs.get("tempRange", "")
        print(f"Проверка температуры среды: требуется {temperature_min}-{temperature_max}, спецификация: {temp_range}")
        if temp_range:
            spec_temp_min = _extract_min_value(temp_range)
            spec_temp_max = _extract_max_value(temp_range)
            
            if temperature_min is not None and temperature_min < spec_temp_min:
                print(f"ОТКЛОНЕНО: минимальная температура {temperature_min} < {spec_temp_min}")
                return False
            if temperature_max is not None and temperature_max > spec_temp_max:
                print(f"ОТКЛОНЕНО: максимальная температура {temperature_max} > {spec_temp_max}")
                return False
    
    # Проверка температуры окружающей среды (поддержка обеих версий полей)
    ambient_temp_min = safe_float(params.ambient_temp_min or params.ambient_temperature_min)
    ambient_temp_max = safe_float(params.ambient_temp_max or params.ambient_temperature_max)
    if ambient_temp_min is not None or ambient_temp_max is not None:
        ambient_temp_range = specs.get("ambientTempRange", "")
        print(f"Проверка температуры окружающей среды: требуется {ambient_temp_min}-{ambient_temp_max}, спецификация: {ambient_temp_range}")
        if ambient_temp_range:
            spec_ambient_min = _extract_min_value(ambient_temp_range)
            spec_ambient_max = _extract_max_value(ambient_temp_range)
            
            if ambient_temp_min is not None and ambient_temp_min < spec_ambient_min:
                print(f"ОТКЛОНЕНО: минимальная температура окружающей среды {ambient_temp_min} < {spec_ambient_min}")
                return False
            if ambient_temp_max is not None and ambient_temp_max > spec_ambient_max:
                print(f"ОТКЛОНЕНО: максимальная температура окружающей среды {ambient_temp_max} > {spec_ambient_max}")
                return False
    
    # Проверка расхода с учетом конвертации для жидкостей
    flow_min = safe_float(params.flow_min)
    flow_max = safe_float(params.flow_max)
    if flow_min is not None or flow_max is not None:
        flow_range = specs.get("flowRange", "")
        print(f"Проверка расхода: требуется {flow_min}-{flow_max} {params.flow_unit}, спецификация: {flow_range}")
        if flow_range:
            spec_flow_min = _extract_min_value(flow_range)
            spec_flow_max = _extract_max_value(flow_range)
            
            # Конвертация массового расхода в объемный для жидкостей
            user_flow_min = flow_min
            user_flow_max = flow_max
            
            density_min = safe_float(params.density_min)
            density_max = safe_float(params.density_max)
            if params.medium == "liquid" and params.flow_unit == "кг/ч" and density_min is not None and density_min > 0:
                # Конвертируем кг/ч в м³/ч используя среднюю плотность (как в gui_app.py)
                avg_density = density_min
                if density_max is not None and density_max > 0:
                    avg_density = (density_min + density_max) / 2
                
                print(f"Конвертация массового расхода: плотность {avg_density} кг/м³")
                if user_flow_min is not None:
                    old_min = user_flow_min
                    user_flow_min = user_flow_min / avg_density
                    print(f"Конвертация: {old_min} кг/ч -> {user_flow_min} м³/ч")
                if user_flow_max is not None:
                    old_max = user_flow_max
                    user_flow_max = user_flow_max / avg_density
                    print(f"Конвертация: {old_max} кг/ч -> {user_flow_max} м³/ч")
            
            print(f"Сравнение расхода: пользователь {user_flow_min}-{user_flow_max}, спецификация {spec_flow_min}-{spec_flow_max}")
            if user_flow_min is not None and user_flow_min < spec_flow_min:
                print(f"ОТКЛОНЕНО: минимальный расход {user_flow_min} < {spec_flow_min}")
                return False
            if user_flow_max is not None and user_flow_max > spec_flow_max:
                print(f"ОТКЛОНЕНО: максимальный расход {user_flow_max} > {spec_flow_max}")
                return False
    
    # Проверка точности
    accuracy = safe_float(params.accuracy)
    if accuracy is not None:
        accuracy_range = specs.get("accuracy", "")
        print(f"Проверка точности: требуется {accuracy}, спецификация: {accuracy_range}")
        if accuracy_range:
            spec_accuracy_min = _extract_min_value(accuracy_range)
            
            # Для точности проверяем, что требуемая точность не хуже (меньше) минимальной спецификации
            if accuracy < spec_accuracy_min:
                print(f"ОТКЛОНЕНО: требуемая точность {accuracy} < минимальной спецификации {spec_accuracy_min}")
                return False
    
    # Проверка плотности для жидкостей
    density_min = safe_float(params.density_min)
    density_max = safe_float(params.density_max)
    print(f"DEBUG плотность: medium={params.medium}, density_min={params.density_min}→{density_min}, density_max={params.density_max}→{density_max}")
    if params.medium == "liquid" and (density_min is not None or density_max is not None):
        density_range = specs.get("densityRange", "")
        print(f"Проверка плотности: требуется {density_min}-{density_max}, спецификация: {density_range}")
        if density_range:
            spec_density_min = _extract_min_value(density_range)
            spec_density_max = _extract_max_value(density_range)
            
            if density_min is not None and density_min < spec_density_min:
                print(f"ОТКЛОНЕНО: минимальная плотность {density_min} < {spec_density_min}")
                return False
            if density_max is not None and density_max > spec_density_max:
                print(f"ОТКЛОНЕНО: максимальная плотность {density_max} > {spec_density_max}")
                return False
    
    # Проверка диаметра
    diameter = safe_float(params.diameter)
    if diameter is not None:
        diameter_range = specs.get("diameter", "")
        print(f"Проверка диаметра: требуется {diameter}, спецификация: {diameter_range}")
        if diameter_range:
            spec_diameter_min = _extract_min_value(diameter_range)
            spec_diameter_max = _extract_max_value(diameter_range)
            
            if diameter < spec_diameter_min or diameter > spec_diameter_max:
                print(f"ОТКЛОНЕНО: диаметр {diameter} не в диапазоне {spec_diameter_min}-{spec_diameter_max}")
                return False
    
    print(f"ПОДХОДИТ: {equipment_name} прошло все проверки")
    return True

def get_equipment_rejection_reasons(equipment: Dict[str, Any], params: EquipmentParams) -> List[str]:
    """Возвращает список причин, по которым оборудование не подходит"""
    reasons = []
    specs = equipment.get("specs", {})
    
    def safe_float(value):
        """Безопасное преобразование в float с обработкой строк"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                # Заменяем запятые на точки для корректного парсинга
                return float(value.replace(',', '.'))
            except ValueError:
                return None
        return None
    
    # Проверка давления
    pressure_min = safe_float(params.pressure_min)
    pressure_max = safe_float(params.pressure_max)
    if pressure_min is not None or pressure_max is not None:
        pressure_range = specs.get("pressureRange", "")
        if pressure_range:
            spec_pressure_min = _extract_min_value(pressure_range)
            spec_pressure_max = _extract_max_value(pressure_range)
            
            if pressure_min is not None and pressure_min < spec_pressure_min:
                reasons.append(f"Минимальное давление ({pressure_min}) ниже спецификации ({spec_pressure_min})")
            if pressure_max is not None and pressure_max > spec_pressure_max:
                reasons.append(f"Максимальное давление ({pressure_max}) выше спецификации ({spec_pressure_max})")
    
    # Проверка температуры среды
    temperature_min = safe_float(params.temperature_min)
    temperature_max = safe_float(params.temperature_max)
    if temperature_min is not None or temperature_max is not None:
        temp_range = specs.get("tempRange", "")
        if temp_range:
            spec_temp_min = _extract_min_value(temp_range)
            spec_temp_max = _extract_max_value(temp_range)
            
            if temperature_min is not None and temperature_min < spec_temp_min:
                reasons.append(f"Минимальная температура среды ({temperature_min}°C) ниже спецификации ({spec_temp_min}°C)")
            if temperature_max is not None and temperature_max > spec_temp_max:
                reasons.append(f"Максимальная температура среды ({temperature_max}°C) выше спецификации ({spec_temp_max}°C)")
    
    # Проверка температуры окружающей среды
    ambient_temperature_min = safe_float(params.ambient_temperature_min or params.ambient_temp_min)
    ambient_temperature_max = safe_float(params.ambient_temperature_max or params.ambient_temp_max)
    if ambient_temperature_min is not None or ambient_temperature_max is not None:
        ambient_temp_range = specs.get("ambientTempRange", "")
        if ambient_temp_range:
            spec_ambient_min = _extract_min_value(ambient_temp_range)
            spec_ambient_max = _extract_max_value(ambient_temp_range)
            
            if ambient_temperature_min is not None and ambient_temperature_min < spec_ambient_min:
                reasons.append(f"Минимальная температура окружающей среды ({ambient_temperature_min}°C) ниже спецификации ({spec_ambient_min}°C)")
            if ambient_temperature_max is not None and ambient_temperature_max > spec_ambient_max:
                reasons.append(f"Максимальная температура окружающей среды ({ambient_temperature_max}°C) выше спецификации ({spec_ambient_max}°C)")
    
    # Проверка расхода с учетом конвертации для жидкостей
    flow_min = safe_float(params.flow_min)
    flow_max = safe_float(params.flow_max)
    if flow_min is not None or flow_max is not None:
        flow_range = specs.get("flowRange", "")
        if flow_range:
            spec_flow_min = _extract_min_value(flow_range)
            spec_flow_max = _extract_max_value(flow_range)
            
            # Конвертация массового расхода в объемный для жидкостей
            user_flow_min = flow_min
            user_flow_max = flow_max
            flow_unit_display = params.flow_unit or "м³/ч"
            
            density_min = safe_float(params.density_min)
            density_max = safe_float(params.density_max)
            if params.medium == "liquid" and params.flow_unit == "кг/ч" and density_min is not None:
                # Конвертируем кг/ч в м³/ч используя среднюю плотность (как в gui_app.py)
                avg_density = density_min
                if density_max is not None and density_max > 0:
                    avg_density = (density_min + density_max) / 2
                
                if user_flow_min is not None:
                    user_flow_min = user_flow_min / avg_density
                if user_flow_max is not None:
                    user_flow_max = user_flow_max / avg_density
                flow_unit_display = "м³/ч (конвертировано из кг/ч)"
            
            if user_flow_min is not None and user_flow_min < spec_flow_min:
                reasons.append(f"Минимальный расход ({user_flow_min} {flow_unit_display}) ниже спецификации ({spec_flow_min} м³/ч)")
            if user_flow_max is not None and user_flow_max > spec_flow_max:
                reasons.append(f"Максимальный расход ({user_flow_max} {flow_unit_display}) выше спецификации ({spec_flow_max} м³/ч)")
    
    # Проверка точности
    accuracy = safe_float(params.accuracy)
    if accuracy is not None:
        accuracy_range = specs.get("accuracy", "")
        if accuracy_range:
            spec_accuracy_min = _extract_min_value(accuracy_range)
            
            # Для точности проверяем, что требуемая точность не хуже (меньше) минимальной спецификации
            if accuracy < spec_accuracy_min:
                reasons.append(f"Требуемая точность ({accuracy}%) хуже минимальной спецификации ({spec_accuracy_min}%)")
    
    # Проверка плотности для жидкостей
    density_min = safe_float(params.density_min)
    density_max = safe_float(params.density_max)
    if params.medium == "liquid" and (density_min is not None or density_max is not None):
        density_range = specs.get("densityRange", "")
        if density_range:
            spec_density_min = _extract_min_value(density_range)
            spec_density_max = _extract_max_value(density_range)
            
            if density_min is not None and density_min < spec_density_min:
                reasons.append(f"Минимальная плотность ({density_min} кг/м³) ниже спецификации ({spec_density_min} кг/м³)")
            if density_max is not None and density_max > spec_density_max:
                reasons.append(f"Максимальная плотность ({density_max} кг/м³) выше спецификации ({spec_density_max} кг/м³)")
    
    # Проверка диаметра
    diameter = safe_float(params.diameter)
    if diameter is not None:
        diameter_range = specs.get("diameter", "")
        if diameter_range:
            spec_diameter_min = _extract_min_value(diameter_range)
            spec_diameter_max = _extract_max_value(diameter_range)
            
            if diameter < spec_diameter_min or diameter > spec_diameter_max:
                reasons.append(f"Диаметр ({diameter} мм) не входит в диапазон спецификации ({spec_diameter_min}-{spec_diameter_max} мм)")
    
    return reasons

def get_recommended_diameter_for_equipment(equipment: Dict[str, Any], params: EquipmentParams) -> str:
    """Расчет рекомендуемого диаметра для конкретного оборудования"""
    try:
        model_name = equipment.get("name", "")
        
        # Проверяем, есть ли у нас параметры расхода
        if not (params.flow_min or params.flow_max):
            return ""
        
        # Вызываем соответствующую функцию в зависимости от модели
        if "CFM" in model_name:
            return get_recommended_diameter_for_cfm(params)
        elif "UFG-F-V" in model_name:
            return get_recommended_diameter_ufgfv(params)
        elif "UFG-F-C" in model_name:
            return get_recommended_diameter_ufgfc(params)
        elif "GFG" in model_name:
            return get_recommended_diameter_gfg(params)
        elif "UFL" in model_name:
            return get_recommended_diameter_ufl_by_formula(equipment, params)
        elif "TFG-S" in model_name or "TFG-H" in model_name:
            return get_recommended_diameter_tfg(equipment, params)
        elif "UFG-H" in model_name:
            return get_recommended_diameter_ufgh(params)
        else:
            return ""
            
    except Exception as e:
        return f"Ошибка при расчете диаметра: {e}"

def get_recommended_diameter_for_cfm(params: EquipmentParams) -> str:
    """Расчет рекомендуемого диаметра для CFM на основе расхода"""
    try:
        # Получаем диапазоны массового расхода по DN из базы данных
        diameter_ranges = []
        
        # Загружаем данные из базы для CFM (находится в liquid)
        cfm_data = equipment_db.get("liquid", [])
        
        for equipment in cfm_data:
            if "CFM" in equipment.get("model", "") or "CFM" in equipment.get("name", ""):
                specs = equipment.get("specs", {})
                # Используем массовые диапазоны расхода по DN
                mass_flow_ranges = specs.get("massFlowRangesByDN", {})
                
                if mass_flow_ranges:
                    for dn, range_str in mass_flow_ranges.items():
                        flow_min = _extract_min_value(range_str)
                        flow_max = _extract_max_value(range_str)
                        diameter_ranges.append(((flow_min, flow_max), dn))
        
        if not diameter_ranges:
            return "Нет данных для расчета диаметра"
        
        # Безопасное преобразование параметров
        def safe_float(value):
            """Безопасное преобразование в float с обработкой строк"""
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.replace(',', '.'))
                except ValueError:
                    return None
            return None
        
        # Получаем расход пользователя
        flow_min = safe_float(params.flow_min) or 0
        flow_max = safe_float(params.flow_max) or float('inf')
        
        # Конвертация единиц измерения в т/ч (как в базе данных)
        if params.flow_unit == "кг/ч":
            # Конвертируем кг/ч в т/ч
            flow_min = flow_min / 1000 if flow_min else 0
            flow_max = flow_max / 1000 if flow_max != float('inf') else float('inf')
        elif params.flow_unit == "ст.м³/ч":
            # Конвертация ст.м³/ч уже выполнена ранее, пропускаем
            pass
            
            # Теперь конвертируем м³/ч в т/ч используя плотность
            density_min = safe_float(params.density_min) or 1000
            density_max = safe_float(params.density_max)
            avg_density = density_min
            if density_max is not None and density_max > 0:
                avg_density = (density_min + density_max) / 2
            
            flow_min = flow_min * avg_density / 1000 if flow_min else 0
            flow_max = flow_max * avg_density / 1000 if flow_max != float('inf') else float('inf')
        elif params.flow_unit == "м³/ч":
            # Конвертируем м³/ч в т/ч используя плотность
            density_min = safe_float(params.density_min) or 1000
            density_max = safe_float(params.density_max)
            avg_density = density_min
            if density_max is not None and density_max > 0:
                avg_density = (density_min + density_max) / 2
            
            flow_min = flow_min * avg_density / 1000 if flow_min else 0
            flow_max = flow_max * avg_density / 1000 if flow_max != float('inf') else float('inf')
        # Если уже т/ч, оставляем как есть
        
        # Поиск подходящих диаметров
        suitable_diameters = []
        for (range_min, range_max), diameter in diameter_ranges:
            if flow_min >= range_min and flow_max <= range_max:
                suitable_diameters.append((range_min, diameter, range_min, range_max))
        
        if suitable_diameters:
            # Возвращаем минимальный подходящий диаметр
            min_dn = min(suitable_diameters, key=lambda x: x[0])[1]
            return f"Рекомендуемый диаметр: {min_dn}"
        
        # Если нет полностью подходящих, ищем частично пересекающиеся
        partials = []
        for (range_min, range_max), diameter in diameter_ranges:
            if flow_min <= range_max and flow_max >= range_min:
                partials.append((range_min, diameter, range_min, range_max))
        
        if partials:
            messages = []
            for _, dn, dn_min, dn_max in partials:
                reasons = []
                if flow_min < dn_min:
                    reasons.append(f"минимальный расход меньше минимального для DN {dn} ({flow_min} < {dn_min})")
                if flow_max > dn_max:
                    reasons.append(f"максимальный расход больше максимального для DN {dn} ({flow_max} > {dn_max})")
                msg = f"Ближайший диаметр: {dn}. " + "; ".join(reasons)
                messages.append(msg)
            return "\n".join(messages)
        
        # Если нет пересечений, находим ближайший
        all_dns = [(range_min, range_max, diameter) for (range_min, range_max), diameter in diameter_ranges]
        min_dn = min(all_dns, key=lambda x: x[0])
        max_dn = max(all_dns, key=lambda x: x[1])
        
        if flow_max < min_dn[0]:
            return f"Расход слишком мал. Минимальный DN: {min_dn[2]} (от {min_dn[0]} т/ч)" 
        elif flow_min > max_dn[1]:
            return f"Расход слишком велик. Максимальный DN: {max_dn[2]} (до {max_dn[1]} т/ч)"
        else:
            return "Нет подходящего диаметра для данного расхода"
            
    except Exception as e:
        return f"Ошибка при расчете диаметра: {e}"

def get_recommended_diameter_ufgfv(params: EquipmentParams) -> str:
    """Расчет рекомендуемого диаметра для UFG-F-V"""
    diameter_ranges = [
        ((1.4, 280), "DN 50"),
        ((3.5, 700), "DN 80"),
        ((5.5, 1100), "DN 100")
    ]
    return _get_dn_by_flow(params, diameter_ranges)

def get_recommended_diameter_ufgfc(params: EquipmentParams) -> str:
    """Расчет рекомендуемого диаметра для UFG-F-C"""
    diameter_ranges = [
        ((1.4, 280), "DN 50"),
        ((3.5, 700), "DN 80"),
        ((5.5, 1100), "DN 100")
    ]
    return _get_dn_by_flow(params, diameter_ranges)

def get_recommended_diameter_gfg(params: EquipmentParams) -> str:
    """Расчет рекомендуемого диаметра для GFG"""
    diameter_ranges = [
        ((0.016, 16), "DN 10"),
        ((0.032, 32), "DN 15"),
        ((0.06, 60), "DN 20"),
        ((0.09, 90), "DN 25"),
        ((0.15, 153), "DN 32"),
        ((0.24, 240), "DN 40"),
        ((0.375, 375), "DN 50"),
        ((0.96, 960), "DN 80"),
        ((1.50, 1500), "DN 100"),
        ((2.25, 2250), "DN 125"),
        ((3.38, 3375), "DN 150"),
        ((6.00, 6000), "DN 200"),
        ((9.38, 9375), "DN 250"),
        ((13.50, 13500), "DN 300"),
        ((18.50, 18500), "DN 350"),
        ((23, 23500), "DN 400"),
        ((30, 30000), "DN 450"),
        ((36, 36000), "DN 500"),
        ((51, 51000), "DN 600"),
        ((70, 70000), "DN 700"),
        ((91, 91000), "DN 800"),
        ((115, 115000), "DN 900"),
        ((145, 145000), "DN 1000"),
        ((175, 175000), "DN 1100"),
        ((205, 205000), "DN 1200"),
        ((280, 280000), "DN 1400")
    ]
    return _get_dn_by_flow(params, diameter_ranges)

def get_recommended_diameter_ufl_by_formula(equipment: Dict[str, Any], params: EquipmentParams) -> str:
    """
    Рассчитывает рекомендуемый диаметр для Turbo Flow UFL на основе формулы
    Q = V * (π * (DN / 1000)²) / 4 * 3600
    
    Args:
        equipment: Словарь с данными прибора из data.json
        params: Параметры поиска
        
    Returns:
        Строка с рекомендацией диаметра
    """
    # Проверяем наличие параметров для расчета
    if 'flowCalculation' not in equipment:
        return "Нет данных для расчета диапазонов расхода"
    
    # Конвертируем массовый расход в объемный, если необходимо
    flow_min_converted = params.flow_min
    flow_max_converted = params.flow_max
    
    # Если выбран ст.м³/ч, конвертируем в м³/ч (рабочие условия)
    if params.flow_unit == 'ст.м³/ч':
        # Стандартные условия: +20°C (293.15 K), 101.325 кПа
        P_st = 101.325  # кПа
        T_st = 293.15   # K (+20°C)
        
        # Рабочее давление (среднее из диапазона) в МПа → кПа
        p_min = float(str(params.pressure_min).replace(',', '.')) if params.pressure_min else 0.1
        p_max = float(str(params.pressure_max).replace(',', '.')) if params.pressure_max else p_min
        P_work = ((p_min + p_max) / 2) * 1000  # МПа → кПа
        
        # Рабочая температура (среднее из диапазона) в °C → K
        t_min = float(str(params.temperature_min).replace(',', '.')) if params.temperature_min else 20
        t_max = float(str(params.temperature_max).replace(',', '.')) if params.temperature_max else t_min
        T_work = ((t_min + t_max) / 2) + 273.15  # °C → K
        
        # Формула: Q_раб = Q_ст × (P_ст / P_раб) × (T_раб / T_ст)
        conversion_factor = (P_st / P_work) * (T_work / T_st)
        
        if params.flow_min:
            flow_min_val = float(str(params.flow_min).replace(',', '.')) if params.flow_min else 0
            flow_min_converted = str(round(flow_min_val * conversion_factor, 4))
        
        if params.flow_max:
            flow_max_val = float(str(params.flow_max).replace(',', '.')) if params.flow_max else float('inf')
            flow_max_converted = str(round(flow_max_val * conversion_factor, 4)) if flow_max_val < float('inf') else str(float('inf'))
    
    # Если выбран массовый расход (кг/ч) для жидкости, конвертируем в объемный (м³/ч)
    elif (params.medium == 'liquid' and 
        params.flow_unit == 'кг/ч' and 
        params.density_min):
        
        # Используем среднюю плотность для конвертации массового расхода в объемный
        density_min = float(params.density_min.replace(',', '.')) if params.density_min else 1000
        density_max = float(params.density_max.replace(',', '.')) if params.density_max else density_min
        avg_density = (density_min + density_max) / 2  # кг/м³
        
        # Конвертация: объемный_расход = массовый_расход / плотность
        # кг/ч / (кг/м³) = м³/ч
        if params.flow_min:
            flow_min_val = float(str(params.flow_min).replace(',', '.')) if params.flow_min else 0
            flow_min_converted = str(flow_min_val / avg_density)
        
        if params.flow_max:
            flow_max_val = float(str(params.flow_max).replace(',', '.')) if params.flow_max else float('inf')
            flow_max_converted = str(flow_max_val / avg_density) if flow_max_val < float('inf') else str(float('inf'))
    
    # Если выбраны стандартные условия для природного газа, конвертируем в рабочие условия
    elif (params.medium == 'gas' and params.application == 'industrial' and 
          params.gas_type == 'natural' and
          params.gas_conditions == 'ст.м³/ч'):
        
        # Получаем параметры давления и температуры
        try:
            # Рабочие условия
            p_work_min = float(params.pressure_min.replace(',', '.')) if params.pressure_min else 0.1  # МПа
            p_work_max = float(params.pressure_max.replace(',', '.')) if params.pressure_max else 0.1
            p_work_avg = (p_work_min + p_work_max) / 2
            
            t_work_min = float(params.temperature_min.replace(',', '.')) if params.temperature_min else 20  # °C
            t_work_max = float(params.temperature_max.replace(',', '.')) if params.temperature_max else 20
            t_work_avg = (t_work_min + t_work_max) / 2 + 273.15  # Конвертируем в Кельвины
            
            # Стандартные условия (20°C, 0.101325 МПа)
            p_std = 0.101325  # МПа
            t_std = 293.15    # К (20°C)
            
            # Формула конвертации: Q_раб = Q_ст × (P_ст/P_раб) × (T_раб/T_ст)
            conversion_factor = (p_std / p_work_avg) * (t_work_avg / t_std)
            
            if params.flow_min:
                flow_min_val = float(str(params.flow_min).replace(',', '.')) if params.flow_min else 0
                flow_min_converted = str(flow_min_val * conversion_factor)
            
            if params.flow_max:
                flow_max_val = float(str(params.flow_max).replace(',', '.')) if params.flow_max else float('inf')
                flow_max_converted = str(flow_max_val * conversion_factor) if flow_max_val < float('inf') else str(float('inf'))
                
        except Exception as e:
            # В случае ошибки используем исходные значения
            pass
    
    # Получаем параметры расчета
    calc_params = equipment['flowCalculation']
    min_velocity = calc_params.get('minVelocity', 0.0625)
    max_velocity = calc_params.get('maxVelocity', 20)
    standard_dns = calc_params.get('standardDNs', [])
    
    # Расчет диапазонов для каждого DN
    diameter_ranges = []
    for dn in standard_dns:
        # Площадь сечения в м²
        area = (math.pi * (dn / 1000)**2) / 4
        
        # Расчет расхода в м³/ч
        q_min = min_velocity * area * 3600
        q_max = max_velocity * area * 3600
        
        diameter_ranges.append(((q_min, q_max), f"DN {dn}"))
    
    # Создаем новый объект params с конвертированными значениями
    converted_params = EquipmentParams(
        medium=params.medium,
        application=params.application,
        gas_type=params.gas_type,
        flow_min=flow_min_converted,
        flow_max=flow_max_converted,
        flow_unit=params.flow_unit,
        flow_conditions=params.flow_conditions,
        pressure_min=params.pressure_min,
        pressure_max=params.pressure_max,
        pressure_unit=params.pressure_unit,
        temperature_min=params.temperature_min,
        temperature_max=params.temperature_max,
        temperature_unit=params.temperature_unit,
        ambient_temp_min=params.ambient_temp_min,
        ambient_temp_max=params.ambient_temp_max,
        ambient_temperature_min=params.ambient_temperature_min,
        ambient_temperature_max=params.ambient_temperature_max,
        accuracy=params.accuracy,
        diameter=params.diameter,
        density_min=params.density_min,
        density_max=params.density_max,
        gas_conditions=params.gas_conditions,
        user_id=params.user_id
    )
    
    return _get_dn_by_flow(converted_params, diameter_ranges, full_cover_only=True)

def get_recommended_diameter_tfg(equipment: Dict[str, Any], params: EquipmentParams) -> str:
    """Расчет рекомендуемого диаметра для TFG"""
    # Используем те же диапазоны, что и для UFL
    diameter_ranges = [
        ((0.11, 35.34), "DN 25"),
        ((0.18, 57.91), "DN 32"),
        ((0.28, 90.48), "DN 40"),
        ((0.44, 141.37), "DN 50"),
        ((0.75, 238.92), "DN 65"),
        ((1.13, 361.91), "DN 80"),
        ((1.77, 565.49), "DN 100"),
        ((2.76, 883.57), "DN 125"),
        ((3.98, 1272.35), "DN 150"),
        ((7.07, 2261.95), "DN 200"),
        ((11.04, 3534.29), "DN 250"),
        ((15.90, 5089.38), "DN 300"),
        ((21.65, 6927.21), "DN 350"),
        ((28.27, 9047.79), "DN 400"),
        ((35.78, 11451.11), "DN 450"),
        ((44.18, 14137.17), "DN 500"),
        ((53.46, 17105.97), "DN 550"),
        ((63.62, 20357.52), "DN 600"),
        ((86.59, 27708.85), "DN 700"),
        ((113.10, 36191.15), "DN 800"),
        ((143.14, 45804.42), "DN 900"),
        ((176.71, 56548.67), "DN 1000"),
        ((213.82, 68423.89), "DN 1100"),
        ((254.47, 81430.08), "DN 1200"),
        ((298.65, 95567.25), "DN 1300"),
        ((346.36, 110835.39), "DN 1400"),
        ((397.61, 127234.50), "DN 1500"),
        ((452.39, 144764.59), "DN 1600")
    ]
    return _get_dn_by_flow(params, diameter_ranges)

def get_recommended_diameter_ufgh(params: EquipmentParams) -> str:
    """Расчет рекомендуемого диаметра для UFG-H"""
    diameter_ranges = [
        ((0.01, 150), "DN 32"),
        ((0.01, 150), "DN 40"),
        ((0.01, 150), "DN 50")
    ]
    return _get_dn_by_flow(params, diameter_ranges)

def _get_dn_by_flow(params: EquipmentParams, diameter_ranges: list, full_cover_only: bool = False) -> str:
    """Общая функция для определения DN по расходу"""
    try:
        # Безопасное преобразование параметров
        def safe_float(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.replace(',', '.'))
                except ValueError:
                    return None
            return None
        
        # Получаем расход пользователя
        flow_min = safe_float(params.flow_min) or 0
        flow_max = safe_float(params.flow_max) or float('inf')
        
        # Конвертация единиц измерения
        density_min = safe_float(params.density_min)
        density_max = safe_float(params.density_max)
        
        if params.flow_unit == "ст.м³/ч":
            # Конвертация ст.м³/ч уже выполнена ранее в find_equipment_with_unsuitable
            pass
        elif params.flow_unit == "кг/ч" and density_min:
            # Конвертируем кг/ч в м³/ч используя среднюю плотность
            avg_density = density_min
            if density_max is not None and density_max > 0:
                avg_density = (density_min + density_max) / 2
            
            flow_min = flow_min / avg_density if flow_min else 0
            flow_max = flow_max / avg_density if flow_max else float('inf')
        
        # Поиск подходящих диаметров
        suitable_diameters = []
        for (range_min, range_max), diameter in diameter_ranges:
            if full_cover_only:
                # Для UFL требуется полное соответствие диапазону
                if flow_min >= range_min and flow_max <= range_max:
                    suitable_diameters.append((range_min, diameter))
            else:
                # Для других моделей достаточно пересечения диапазонов
                if flow_min >= range_min and flow_max <= range_max:
                    suitable_diameters.append(diameter)
        
        if suitable_diameters:
            if full_cover_only:
                # Выбираем минимальный подходящий DN
                min_dn = min(suitable_diameters, key=lambda x: x[0])[1]
                return f"Рекомендуемый диаметр: {min_dn}"
            else:
                return f"Рекомендуемый диаметр: {suitable_diameters[0]}"
        
        # Если нет полностью подходящих, ищем частично пересекающиеся
        partials = []
        for (range_min, range_max), diameter in diameter_ranges:
            if flow_min <= range_max and flow_max >= range_min:
                partials.append((diameter, range_min, range_max))
        
        if partials:
            diameter, dn_min, dn_max = partials[0]
            reasons = []
            if flow_min < dn_min:
                reasons.append(f"минимальный расход меньше минимального для {diameter} ({flow_min} < {dn_min})")
            if flow_max > dn_max:
                reasons.append(f"максимальный расход больше максимального для {diameter} ({flow_max} > {dn_max})")
            return f"Ближайший диаметр: {diameter}. " + "; ".join(reasons)
        
        return "Нет подходящего диаметра для данного расхода"
        
    except Exception as e:
        return f"Ошибка при расчете диаметра: {e}"

def _extract_min_value(range_str: str) -> float:
    """Извлекает минимальное значение из строки диапазона"""
    try:
        if not range_str or range_str.strip() == "":
            return 0
        
        # Преобразуем запятые в точки для корректной обработки чисел
        range_str = str(range_str).replace(',', '.')
        
        # Заменяем длинное тире на обычный дефис
        range_str = range_str.replace('–', '-').replace('—', '-').replace('…', '-')
        
        # Удаляем символ ±
        range_str = range_str.replace('±', '')
        
        import re
        
        # Специальная обработка для диапазонов с явным указанием "от" и "до"
        if 'от' in range_str.lower() and 'до' in range_str.lower():
            # Ищем паттерн "от X до Y"
            match = re.search(r'от\s*([+-]?\d+(?:\.\d+)?)\s*до\s*([+-]?\d+(?:\.\d+)?)', range_str.lower())
            if match:
                return float(match.group(1))
        
        # Простой случай: "X-Y МПа" или "X...Y МПа"
        simple_range_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*[-–—]\s*([+-]?\d+(?:\.\d+)?)', range_str)
        if simple_range_match:
            val1 = float(simple_range_match.group(1))
            val2 = float(simple_range_match.group(2))
            return min(val1, val2)
        
        # Ищем все числа в строке
        numbers = re.findall(r'[+-]?\d+(?:\.\d+)?', range_str)
        if not numbers:
            return 0
            
        # Преобразуем строки в числа
        numbers = [float(num) for num in numbers]
        
        # Если только одно число
        if len(numbers) == 1:
            return numbers[0]
        
        # Возвращаем минимальное значение
        return min(numbers)
        
    except Exception as e:
        return 0

def _extract_max_value(range_str: str) -> float:
    """Извлекает максимальное значение из строки диапазона"""
    try:
        if not range_str or range_str.strip() == "":
            return 1000
        
        # Преобразуем запятые в точки для корректной обработки чисел
        range_str = str(range_str).replace(',', '.')
        
        # Заменяем длинное тире на обычный дефис
        range_str = range_str.replace('–', '-').replace('—', '-').replace('…', '-')
        
        # Удаляем символ ±
        range_str = range_str.replace('±', '')
        
        import re
        
        # Специальная обработка для диапазонов с явным указанием "от" и "до"
        if 'от' in range_str.lower() and 'до' in range_str.lower():
            # Ищем паттерн "от X до Y"
            match = re.search(r'от\s*([+-]?\d+(?:\.\d+)?)\s*до\s*([+-]?\d+(?:\.\d+)?)', range_str.lower())
            if match:
                return float(match.group(2))
        
        # Простой случай: "X-Y МПа" или "X...Y МПа"
        simple_range_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*[-–—]\s*([+-]?\d+(?:\.\d+)?)', range_str)
        if simple_range_match:
            val1 = float(simple_range_match.group(1))
            val2 = float(simple_range_match.group(2))
            return max(val1, val2)
        
        # Ищем все числа в строке
        numbers = re.findall(r'[+-]?\d+(?:\.\d+)?', range_str)
        if not numbers:
            return 1000
            
        # Преобразуем строки в числа
        numbers = [float(num) for num in numbers]
        
        # Если только одно число
        if len(numbers) == 1:
            return numbers[0]
        
        # Возвращаем максимальное значение
        return max(numbers)
        
    except Exception as e:
        return 1000

def _is_valid_number(value: str) -> bool:
    """Проверяет, является ли строка корректным числом (целым или с плавающей точкой)"""
    try:
        # Заменяем запятую на точку для поддержки разных форматов ввода
        value = str(value).replace(',', '.')
        float(value)
        return True
    except (ValueError, TypeError):
        return False

def check_range_compatibility(spec_range: str, min_val: Optional[float], max_val: Optional[float]) -> bool:
    """Проверка совместимости диапазонов"""
    if not spec_range:
        return True
    
    try:
        spec_min = _extract_min_value(spec_range)
        spec_max = _extract_max_value(spec_range)
        
        # Проверяем пересечение диапазонов
        if min_val is not None and max_val is not None:
            # Проверяем, что диапазоны пересекаются
            return not (max_val < spec_min or min_val > spec_max)
        elif min_val is not None:
            # Проверяем, что минимальное значение не превышает максимум спецификации
            return min_val <= spec_max
        elif max_val is not None:
            # Проверяем, что максимальное значение не меньше минимума спецификации
            return max_val >= spec_min
        
        return True
    except (ValueError, IndexError):
        # Если не удалось распарсить, считаем совместимым
        return True

def check_accuracy_compatibility(spec_accuracy: str, required_accuracy: float) -> bool:
    """Проверка совместимости точности"""
    if not spec_accuracy:
        return True
    
    try:
        import re
        
        # Удаляем символ процента и лишние символы
        clean_accuracy = spec_accuracy.replace('%', '').replace('±', '')
        
        # Ищем числа в строке точности
        numbers = re.findall(r'[0-9]+[,.]?[0-9]*', clean_accuracy)
        
        if numbers:
            # Берем максимальное значение точности из диапазона
            max_accuracy = max([float(num.replace(',', '.')) for num in numbers])
            
            # Проверяем, что требуемая точность не превышает максимальную точность оборудования
            return required_accuracy <= max_accuracy
        
        return True
    except (ValueError, IndexError):
        return True

def calculate_compatibility_score(equipment: Dict[str, Any], params: EquipmentParams) -> float:
    """Расчет рейтинга соответствия оборудования параметрам (0-100)"""
    score = 0.0
    max_score = 0.0
    specs = equipment.get("specs", {})
    
    # Проверка расхода (вес: 30)
    if params.flow_min is not None or params.flow_max is not None:
        max_score += 30
        flow_range = specs.get("flowRange", "")
        if check_range_compatibility(flow_range, params.flow_min, params.flow_max):
            score += 30
    
    # Проверка давления (вес: 25)
    if params.pressure_min is not None or params.pressure_max is not None:
        max_score += 25
        pressure_range = specs.get("pressureRange", "")
        if check_range_compatibility(pressure_range, params.pressure_min, params.pressure_max):
            score += 25
    
    # Проверка температуры (вес: 20)
    if params.temperature_min is not None or params.temperature_max is not None:
        max_score += 20
        temp_range = specs.get("tempRange", "")
        if check_range_compatibility(temp_range, params.temperature_min, params.temperature_max):
            score += 20
    
    # Проверка диаметра (вес: 15)
    if params.diameter is not None:
        max_score += 15
        diameter_range = specs.get("diameter", "")
        if check_range_compatibility(diameter_range, params.diameter, params.diameter):
            score += 15
    
    # Проверка точности (вес: 10)
    if params.accuracy is not None:
        max_score += 10
        accuracy_range = specs.get("accuracy", "")
        if check_accuracy_compatibility(accuracy_range, params.accuracy):
            score += 10
    
    # Возвращаем процент соответствия
    return (score / max_score * 100) if max_score > 0 else 100

# API для получения данных для фронтенда
@app.get("/api/equipment/categories")
async def get_equipment_categories():
    """Получение категорий оборудования"""
    return {
        "media": ["gas", "liquid"],
        "applications": ["industrial", "utility"],
        "gas_types": ["natural", "technological"]
    }

@app.get("/api/equipment/{equipment_id}")
async def get_equipment_details(equipment_id: str):
    """Получение детальной информации об оборудовании"""
    # Поиск оборудования по ID во всех категориях
    for medium in equipment_db.values():
        if isinstance(medium, dict):
            for app_data in medium.values():
                if isinstance(app_data, dict):
                    for gas_data in app_data.values():
                        if isinstance(gas_data, list):
                            for equipment in gas_data:
                                if equipment.get("id") == equipment_id:
                                    # Добавляем расчетные параметры
                                    equipment_details = equipment.copy()
                                    equipment_details["calculated_params"] = calculate_equipment_parameters(equipment)
                                    return equipment_details
                elif isinstance(app_data, list):
                    for equipment in app_data:
                        if equipment.get("id") == equipment_id:
                            # Добавляем расчетные параметры
                            equipment_details = equipment.copy()
                            equipment_details["calculated_params"] = calculate_equipment_parameters(equipment)
                            return equipment_details
    
    raise HTTPException(status_code=404, detail="Оборудование не найдено")

@app.post("/api/generate-questionnaire")
async def generate_questionnaire(request: QuestionnaireRequest):
    """Генерация опросного листа для отправки в 1С"""
    try:
        # Генерируем уникальный ID для опросного листа
        questionnaire_id = str(uuid.uuid4())
        
        print(f"DEBUG: Поиск оборудования с ID: {request.equipment_id}")
        print(f"DEBUG: Структура equipment_db: {list(equipment_db.keys())}")
        
        # Получаем информацию об оборудовании
        equipment_details = None
        for app_name, app_data in equipment_db.items():
            print(f"DEBUG: Проверяем категорию: {app_name}")
            if isinstance(app_data, dict):
                for category, equipment_list in app_data.items():
                    print(f"DEBUG: Проверяем подкатегорию: {category}")
                    if isinstance(equipment_list, list):
                        print(f"DEBUG: Найдено {len(equipment_list)} единиц оборудования")
                        for equipment in equipment_list:
                            print(f"DEBUG: Проверяем оборудование с ID: {equipment.get('id')}")
                            if equipment.get("id") == request.equipment_id:
                                equipment_details = equipment
                                print(f"DEBUG: Найдено оборудование: {equipment.get('name')}")
                                break
                    elif isinstance(equipment_list, dict):
                        # Обработка третьего уровня (например, gas -> industrial -> natural)
                        print(f"DEBUG: Подкатегория {category} содержит подтипы: {list(equipment_list.keys())}")
                        for subtype, subtype_items in equipment_list.items():
                            print(f"DEBUG: Проверяем подтип: {subtype}")
                            if isinstance(subtype_items, list):
                                print(f"DEBUG: В подтипе {subtype} найдено {len(subtype_items)} единиц оборудования")
                                for equipment in subtype_items:
                                    print(f"DEBUG: Проверяем оборудование с ID: {equipment.get('id')} в подтипе {subtype}")
                                    if equipment.get("id") == request.equipment_id:
                                        equipment_details = equipment
                                        print(f"DEBUG: Найдено оборудование: {equipment.get('name')}")
                                        break
                            if equipment_details:
                                break
                    if equipment_details:
                        break
            elif isinstance(app_data, list):
                for equipment in app_data:
                    if equipment.get("id") == request.equipment_id:
                        equipment_details = equipment
                        break
            if equipment_details:
                break
        
        if not equipment_details:
            raise HTTPException(status_code=404, detail="Оборудование не найдено")
        
        # Формируем данные опросного листа
        questionnaire_data = {
            "id": questionnaire_id,
            "timestamp": datetime.now().isoformat(),
            "equipment": {
                "id": request.equipment_id,
                "name": request.equipment_name,
                "details": equipment_details
            },
            "search_parameters": request.search_params,
            "user_login": request.user_login,  # Добавляем логин пользователя
            "equipment_type": request.equipment_type,  # Тип оборудования (flowmeter/densitometer)
            "status": "generated"
        }
        
        # Удаляем пустые значения
        def remove_empty_values(obj):
            if isinstance(obj, dict):
                return {k: remove_empty_values(v) for k, v in obj.items() if v is not None and v != ""}
            elif isinstance(obj, list):
                return [remove_empty_values(item) for item in obj if item is not None and item != ""]
            return obj
        
        questionnaire_data = remove_empty_values(questionnaire_data)
        
        return JSONResponse(content={
            "success": True,
            "questionnaire_id": questionnaire_id,
            "data": questionnaire_data
        })
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.post("/api/submit-modular-request")
async def submit_modular_request(
    fullname: str = Form(...),
    organization: str = Form(...),
    position: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    comment: str = Form(""),
    equipment_type: str = Form("modular"),  # Тип оборудования (по умолчанию modular)
    tz_file: UploadFile = File(...)
):
    """Обработка заявки на различные типы оборудования с отправкой на email"""
    try:
        logger.info(f"Получена заявка на {equipment_type} от {fullname} ({organization})")
        
        # Проверка размера файла (макс 10 МБ)
        file_content = await tz_file.read()
        file_size_mb = len(file_content) / (1024 * 1024)
        
        if file_size_mb > 10:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "Размер файла превышает 10 МБ"
                }
            )
        
        # Сохраняем файл во временную папку
        upload_dir = Path("received_data/modular_requests")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{tz_file.filename}"
        file_path = upload_dir / safe_filename
        
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        # Сохраняем данные заявки в JSON
        request_data = {
            "timestamp": datetime.now().isoformat(),
            "equipment_type": equipment_type,
            "fullname": fullname,
            "organization": organization,
            "position": position,
            "phone": phone,
            "email": email,
            "comment": comment,
            "file_name": tz_file.filename,
            "file_path": str(file_path),
            "file_size_mb": round(file_size_mb, 2)
        }
        
        json_path = upload_dir / f"{timestamp}_data.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(request_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Заявка сохранена: {json_path}")
        logger.info(f"Файл сохранен: {file_path} ({file_size_mb:.2f} МБ)")
        
        # Отправка email с заявкой
        email_sent = False
        email_error = None
        
        try:
            from email_config import (
                SEND_EMAIL, SMTP_SERVER, SMTP_PORT, 
                SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL, CC_EMAILS,
                EMAIL_SUBJECT_TEMPLATE, EMAIL_BODY_TEMPLATE,
                EQUIPMENT_EMAIL_ROUTES
            )
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
            
            if SEND_EMAIL:
                logger.info("Начало отправки email...")
                
                # Определяем получателей в зависимости от типа оборудования
                if equipment_type in EQUIPMENT_EMAIL_ROUTES:
                    route = EQUIPMENT_EMAIL_ROUTES[equipment_type]
                    to_email = route.get("to", RECEIVER_EMAIL)
                    cc_emails = route.get("cc", CC_EMAILS)
                    logger.info(f"📧 Используется маршрут для '{equipment_type}': to={to_email}, cc={cc_emails}")
                else:
                    to_email = RECEIVER_EMAIL
                    cc_emails = CC_EMAILS
                    logger.info(f"📧 Используется маршрут по умолчанию: to={to_email}, cc={cc_emails}")
                
                # Формируем сообщение
                msg = MIMEMultipart()
                msg['From'] = SENDER_EMAIL
                msg['To'] = to_email
                if cc_emails:
                    msg['Cc'] = ', '.join(cc_emails)
                
                msg['Subject'] = EMAIL_SUBJECT_TEMPLATE.format(fullname=fullname)
                
                # Формируем тело письма
                comment_section = f"Комментарий: {comment}" if comment else "Комментарий не указан"
                body = EMAIL_BODY_TEMPLATE.format(
                    fullname=fullname,
                    organization=organization,
                    position=position,
                    phone=phone,
                    email=email,
                    comment_section=comment_section,
                    filename=tz_file.filename,
                    filesize=f"{file_size_mb:.2f}",
                    timestamp=datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                )
                
                msg.attach(MIMEText(body, 'plain', 'utf-8'))
                
                # Прикрепляем файл ТЗ
                with open(file_path, "rb") as attachment:
                    # Определяем MIME-тип на основе расширения файла
                    import mimetypes
                    mime_type, _ = mimetypes.guess_type(tz_file.filename)
                    if mime_type is None:
                        mime_type = 'application/octet-stream'
                    
                    main_type, sub_type = mime_type.split('/', 1)
                    part = MIMEBase(main_type, sub_type)
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    
                    # Используем правильное кодирование имени файла для поддержки кириллицы
                    from email.utils import encode_rfc2231
                    encoded_filename = encode_rfc2231(tz_file.filename, charset='utf-8')
                    part.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=encoded_filename
                    )
                    msg.attach(part)
                
                # Отправляем email
                # Используем SMTP_SSL для порта 465, SMTP для порта 587
                if SMTP_PORT == 465:
                    # SSL соединение (для Mail.ru, Yandex по умолчанию)
                    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        
                        # Список всех получателей (основной + копии)
                        recipients = [to_email] + cc_emails
                        server.send_message(msg, to_addrs=recipients)
                else:
                    # TLS соединение (для порта 587)
                    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                        server.starttls()
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        
                        # Список всех получателей (основной + копии)
                        recipients = [to_email] + cc_emails
                        server.send_message(msg, to_addrs=recipients)
                
                email_sent = True
                logger.info(f"✅ Email успешно отправлен на {to_email}" + 
                           (f" (копия: {', '.join(cc_emails)})" if cc_emails else ""))
            else:
                logger.info("⚠️ Отправка email отключена в конфигурации (SEND_EMAIL=False)")
                
        except ImportError:
            logger.warning("⚠️ Файл email_config.py не найден. Email не отправлен.")
            email_error = "Конфигурация email не настроена"
        except Exception as email_ex:
            logger.error(f"❌ Ошибка отправки email: {str(email_ex)}")
            email_error = str(email_ex)
        
        # Формируем ответ с информацией об отправке email
        response_message = "Заявка успешно принята и сохранена"
        if email_sent:
            response_message += ". Email отправлен."
        elif email_error:
            response_message += f". Email не отправлен: {email_error}"
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": response_message,
                "request_id": timestamp,
                "email_sent": email_sent
            }
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке заявки на блочно-модульные изделия: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка сервера: {str(e)}"
            }
        )


def _spu_absolute_url(request: Request, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = str(request.base_url).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _spu_fmt_num_ru(s: str) -> str:
    return (s or "").strip().replace(".", ",")


def _spu_flow_range_display(flow_range: str) -> str:
    raw = (flow_range or "").strip()
    if "-" in raw:
        a, b = raw.split("-", 1)
        return f"{_spu_fmt_num_ru(a)} — {_spu_fmt_num_ru(b)} м³/ч"
    return raw


def _spu_accuracy_display(accuracy: str) -> str:
    a = (accuracy or "").strip()
    if not a:
        return "Не указана"
    return f"±{_spu_fmt_num_ru(a)}%"


_SPU3_FLOW = {"0.016-16", "0.25-25", "0.04-40", "0.1-100"}
_SPU5_FLOW = {"0.03-25", "0.03-70"}
_SPU5_POSTS = {"6", "10", "15", "23"}
_SPU5_LINES = {"1", "2"}
_SPU7_DIAM_NOZZLES = {15, 20, 25, 32, 40, 50, 80, 100, 150, 200}
_SPU7_DIAM_MASTERS = _SPU7_DIAM_NOZZLES | {250}
_SPU7_ACCURACY_NOZZLES = {"0.2", "0.25", "0.3"}


class SpuCardRequest(BaseModel):
    """Параметры карточки СПУ (ветка «Газ» на сайте). Все поля кроме meter_type / installation_type — по необходимости."""

    model_config = ConfigDict(populate_by_name=True)
    meter_type: Literal["domestic", "industrial"]
    installation_type: Literal["stationary", "portable"]

    flow_range: Optional[str] = None
    pressure_limit: Optional[str] = None
    accuracy: Optional[str] = None

    posts: Optional[str] = None
    lines: Optional[str] = None

    modification: Optional[Literal["nozzles", "masters"]] = None
    diameter: Optional[int] = None


class SpuCardResponse(BaseModel):
    name: str
    type: str
    modification: Optional[str] = None
    diameter: Optional[str] = None
    counters: str
    flow_range: str
    accuracy: str
    image_path: str
    image_url: str
    equipment_key: Literal["spu3", "spu5", "spu7"]


class SpuApplicationRequestJson(BaseModel):
    """
    Заявка на поверочную установку СПУ.
    Либо `selection` (как POST /api/spu/card), либо готовые equipment_name + specifications.
    """

    fullname: str = Field(..., min_length=1)
    contact: str = Field(..., min_length=1)
    comment: str = ""
    source: Optional[str] = Field(
        default=None,
        description="Метка внешней системы (бот, CRM и т.д.)",
    )
    equipment_name: Optional[str] = None
    specifications: Optional[Dict[str, str]] = None
    equipment_key: Optional[Literal["spu3", "spu5", "spu7"]] = None
    selection: Optional[SpuCardRequest] = None

    @model_validator(mode="after")
    def equipment_or_selection(self) -> "SpuApplicationRequestJson":
        if self.selection is None and (
            not self.equipment_name or not self.specifications
        ):
            raise ValueError(
                "Укажите selection (параметры подбора, как для POST /api/spu/card) "
                "или пару equipment_name и specifications"
            )
        return self


class HouseholdGasMeterItem(BaseModel):
    name: str = Field(..., min_length=1)
    price: int = Field(..., ge=0)
    quantity: int = Field(default=1, ge=1)


class HouseholdGasMeterRequestJson(BaseModel):
    """Тело JSON для заявки с внешнего проекта (файл ТЗ через JSON не передаётся)."""
    fullname: str = Field(..., min_length=1)
    contact: str = Field(..., min_length=1)
    comment: str = ""
    organization: Optional[str] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    selected_items: Optional[List[HouseholdGasMeterItem]] = None
    source: Optional[str] = Field(
        default=None,
        description="Метка внешней системы (бот, CRM и т.д.)",
    )


def _format_request_extra_for_email(extra: Dict[str, Any]) -> str:
    if not extra:
        return ""
    lines: List[str] = ["", "══════════════════════════════════════════", "📋 ДОПОЛНИТЕЛЬНО", "══════════════════════════════════════════"]
    for key, value in extra.items():
        if value is None or value == "" or value == []:
            continue
        if key == "selected_items" and isinstance(value, list):
            lines.append("Позиции из прайса:")
            for i, item in enumerate(value, 1):
                if isinstance(item, dict):
                    name = item.get("name", "")
                    price = item.get("price", "")
                    qty = item.get("quantity", 1)
                    lines.append(f"  {i}. {name} — {price} ₽ × {qty}")
                else:
                    lines.append(f"  {i}. {item}")
            continue
        label = key.replace("_", " ").capitalize()
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


async def _submit_simple_contact_request(
    *,
    equipment_type: str,
    equipment_name: str,
    storage_subdir: str,
    json_filename_prefix: str,
    email_subject: str,
    email_route_key: str,
    fullname: str,
    contact: str,
    comment: str,
    tz_file: Optional[UploadFile],
    extra_data: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """Сохранение заявки (JSON + опциональный файл) и отправка email по образцу verification-liquid."""
    fullname_clean = fullname.strip()
    contact_clean = contact.strip()
    comment_clean = (comment or "").strip()
    if not fullname_clean or not contact_clean:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Укажите ФИО и контакт (email или телефон)."},
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir = Path(storage_subdir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_saved_name: Optional[str] = None
    file_saved_path: Optional[str] = None
    file_size_mb: float = 0.0

    if tz_file and tz_file.filename:
        raw = await tz_file.read()
        file_size_mb = len(raw) / (1024 * 1024)
        if file_size_mb > 10:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Размер файла превышает 10 МБ"},
            )
        safe_name = f"{timestamp}_{tz_file.filename}"
        file_path = upload_dir / safe_name
        with open(file_path, "wb") as f:
            f.write(raw)
        file_saved_name = tz_file.filename
        file_saved_path = str(file_path)

    request_data: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "equipment_type": equipment_type,
        "equipment_name": equipment_name,
        "fullname": fullname_clean,
        "contact": contact_clean,
        "comment": comment_clean,
        "file_name": file_saved_name,
        "file_path": file_saved_path,
        "file_size_mb": round(file_size_mb, 2) if file_saved_name else None,
    }
    if extra_data:
        request_data.update(extra_data)

    json_path = upload_dir / f"{json_filename_prefix}_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Заявка ({equipment_type}) сохранена: {json_path}")

    email_sent = False
    email_error: Optional[str] = None

    try:
        from email_config import (
            SEND_EMAIL,
            SMTP_SERVER,
            SMTP_PORT,
            SENDER_EMAIL,
            SENDER_PASSWORD,
            RECEIVER_EMAIL,
            CC_EMAILS,
            EQUIPMENT_EMAIL_ROUTES,
        )
        from email.mime.base import MIMEBase
        from email import encoders

        if SEND_EMAIL:
            route = EQUIPMENT_EMAIL_ROUTES.get(email_route_key) or EQUIPMENT_EMAIL_ROUTES.get(
                equipment_type, {}
            )
            to_email = route.get("to", RECEIVER_EMAIL)
            cc_emails = route.get("cc", CC_EMAILS)

            msg = MIMEMultipart()
            msg["From"] = SENDER_EMAIL
            msg["To"] = to_email
            if cc_emails:
                msg["Cc"] = ", ".join(cc_emails)
            msg["Subject"] = email_subject

            extra_block = _format_request_extra_for_email(extra_data or {})
            body = f"""
Новая заявка: {equipment_name}

══════════════════════════════════════════
👤 КОНТАКТНЫЕ ДАННЫЕ
══════════════════════════════════════════
ФИО: {fullname_clean}
E-mail или телефон: {contact_clean}

Комментарий: {comment_clean if comment_clean else 'Не указан'}
{extra_block}

══════════════════════════════════════════
📎 ТЕХНИЧЕСКОЕ ЗАДАНИЕ
══════════════════════════════════════════
{
                f"Файл прикреплён: {file_saved_name} ({file_size_mb:.2f} МБ)"
                if file_saved_name
                else "Файл не приложён"
            }

══════════════════════════════════════════
⏰ Время заявки: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
══════════════════════════════════════════

---
Сообщение сформировано автоматически системой подбора оборудования
Турбулентность-Дон | www.turbo-don.ru
"""
            msg.attach(MIMEText(body.strip(), "plain", "utf-8"))

            if file_saved_path and file_saved_name:
                import mimetypes

                mime_type, _ = mimetypes.guess_type(file_saved_name)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                main_type, sub_type = mime_type.split("/", 1)
                with open(file_saved_path, "rb") as attachment:
                    part = MIMEBase(main_type, sub_type)
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    from email.utils import encode_rfc2231

                    enc_fn = encode_rfc2231(file_saved_name, charset="utf-8")
                    part.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=enc_fn,
                    )
                    msg.attach(part)

            recipients = [to_email] + (cc_emails if cc_emails else [])
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg, to_addrs=recipients)
            else:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg, to_addrs=recipients)
            email_sent = True
            logger.info(f"✅ Email ({equipment_type}) отправлен на {to_email}")

    except ImportError:
        logger.warning("⚠️ email_config недоступен. Email не отправлен.")
        email_error = "Конфигурация email не настроена"
    except Exception as email_ex:
        logger.error(f"❌ Ошибка отправки email ({equipment_type}): {email_ex}")
        email_error = str(email_ex)

    resp_msg = "Заявка успешно принята и сохранена"
    if email_sent:
        resp_msg += ". Email отправлен."
    elif email_error:
        resp_msg += f". Email не отправлен: {email_error}"

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "message": resp_msg,
            "request_id": timestamp,
            "saved_json": str(json_path),
            "email_sent": email_sent,
        },
    )


def _build_spu_card(req: SpuCardRequest, request: Request) -> SpuCardResponse:
    mt = req.meter_type
    it = req.installation_type

    if mt == "industrial" and it == "portable":
        raise HTTPException(
            status_code=422,
            detail="Для промышленных счётчиков доступна только стационарная установка (СПУ-7).",
        )

    if mt == "domestic" and it == "portable":
        fr = (req.flow_range or "").strip()
        pl = (req.pressure_limit or "").strip()
        acc = (req.accuracy or "").strip()
        if fr not in _SPU3_FLOW:
            raise HTTPException(
                status_code=422,
                detail=f"Для СПУ-3 укажите flow_range из {_SPU3_FLOW}, плюс pressure_limit и accuracy.",
            )
        if not pl:
            raise HTTPException(status_code=422, detail="Для СПУ-3 нужен pressure_limit (кПа, как на сайте).")
        if acc not in {"0.3", "0.45"}:
            raise HTTPException(status_code=422, detail="Для СПУ-3 accuracy должен быть 0.3 или 0.45.")
        name = "СПУ-3 — Переносная поверочная установка"
        img = "/static/images/spu3.png"
        return SpuCardResponse(
            name=name,
            type="Переносная",
            modification=None,
            diameter=None,
            counters="Бытовые",
            flow_range=_spu_flow_range_display(fr),
            accuracy=_spu_accuracy_display(acc),
            image_path=img,
            image_url=_spu_absolute_url(request, img),
            equipment_key="spu3",
        )

    if mt == "domestic" and it == "stationary":
        fr = (req.flow_range or "").strip()
        posts = (req.posts or "").strip()
        lines = (req.lines or "").strip()
        if fr not in _SPU5_FLOW:
            raise HTTPException(
                status_code=422,
                detail=f"Для СПУ-5 укажите flow_range из {_SPU5_FLOW}, posts и lines.",
            )
        if posts not in _SPU5_POSTS or lines not in _SPU5_LINES:
            raise HTTPException(
                status_code=422,
                detail=f"Для СПУ-5 posts ∈ {_SPU5_POSTS}, lines ∈ {_SPU5_LINES}.",
            )
        name = "СПУ-5 — Стационарная поверочная установка"
        img = "/static/images/spu5.png"
        return SpuCardResponse(
            name=name,
            type="Стационарная",
            modification=None,
            diameter=None,
            counters="Бытовые",
            flow_range=_spu_flow_range_display(fr),
            accuracy="±0,3%",
            image_path=img,
            image_url=_spu_absolute_url(request, img),
            equipment_key="spu5",
        )

    if mt == "industrial" and it == "stationary":
        mod = req.modification
        diam = req.diameter
        if mod not in ("nozzles", "masters"):
            raise HTTPException(
                status_code=422,
                detail="Для СПУ-7 укажите modification: «nozzles» (сопла) или «masters» (мастер-счётчики).",
            )
        if diam is None:
            raise HTTPException(status_code=422, detail="Для СПУ-7 укажите diameter (мм): целое число, как в списке на сайте.")
        allowed = _SPU7_DIAM_NOZZLES if mod == "nozzles" else _SPU7_DIAM_MASTERS
        if diam not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Для СПУ-7 ({mod}) допустимые diameter (мм): {sorted(allowed)}.",
            )
        mod_name = "Сопла" if mod == "nozzles" else "Мастер-счётчики"
        flow_txt = "0,016 — 1600 м³/ч" if mod == "nozzles" else "0,016 — 5000 м³/ч"
        if mod == "nozzles":
            acc = (req.accuracy or "").strip()
            if acc not in _SPU7_ACCURACY_NOZZLES:
                raise HTTPException(
                    status_code=422,
                    detail=f"Для СПУ-7 (сопла) укажите accuracy из {_SPU7_ACCURACY_NOZZLES}.",
                )
            acc_disp = _spu_accuracy_display(acc)
        else:
            acc_disp = "±0,33%"
        name = "СПУ-7 — Стационарная поверочная установка"
        img = "/static/images/spu7.png"
        return SpuCardResponse(
            name=name,
            type="Стационарная",
            modification=mod_name,
            diameter=f"Ду{diam} мм",
            counters="Бытовые и промышленные",
            flow_range=flow_txt,
            accuracy=acc_disp,
            image_path=img,
            image_url=_spu_absolute_url(request, img),
            equipment_key="spu7",
        )

    raise HTTPException(
        status_code=422,
        detail="Недопустимая комбинация meter_type и installation_type.",
    )


@app.get("/api/spu/card", tags=["api"])
async def api_spu_card_discovery():
    """Подсказка для POST /api/spu/card (карточка СПУ для внешних проектов)."""
    return {
        "use_method": "POST",
        "content_type": "application/json",
        "path": "/api/spu/card",
        "response_fields": [
            "name",
            "type",
            "modification",
            "diameter",
            "counters",
            "flow_range",
            "accuracy",
            "image_path",
            "image_url",
            "equipment_key",
        ],
        "examples": {
            "spu7_masters_dn15": {
                "meter_type": "industrial",
                "installation_type": "stationary",
                "modification": "masters",
                "diameter": 15,
            },
            "spu7_nozzles": {
                "meter_type": "industrial",
                "installation_type": "stationary",
                "modification": "nozzles",
                "diameter": 50,
                "accuracy": "0.3",
            },
            "spu5": {
                "meter_type": "domestic",
                "installation_type": "stationary",
                "flow_range": "0.03-70",
                "posts": "10",
                "lines": "2",
            },
            "spu3": {
                "meter_type": "domestic",
                "installation_type": "portable",
                "flow_range": "0.016-16",
                "pressure_limit": "10",
                "accuracy": "0.3",
            },
        },
    }


@app.post("/api/spu/card", response_model=SpuCardResponse, tags=["api"])
async def api_spu_card(body: SpuCardRequest, request: Request):
    """
    По параметрам подбора СПУ (как на сайте) возвращает данные для карточки:
    название, тип, модификация, диаметр, тип счётчиков, диапазон расходов, погрешность, пути к картинке.
    """
    return _build_spu_card(body, request)


@app.post("/api/spu_card", response_model=SpuCardResponse, tags=["api"])
async def api_spu_card_alias(body: SpuCardRequest, request: Request):
    """Алиас POST /api/spu/card."""
    return _build_spu_card(body, request)


def _spu_specifications_from_card(
    card: SpuCardResponse,
    selection: Optional[SpuCardRequest] = None,
) -> Dict[str, str]:
    """Характеристики для заявки — в том же виде, что на сайте в spuSubmitRequest."""
    specs: Dict[str, str] = {
        "Тип": card.type,
        "Счётчики": card.counters,
        "Диапазон расходов": card.flow_range,
        "Погрешность": card.accuracy,
    }
    if card.modification:
        specs["Модификация"] = card.modification
    if card.diameter:
        specs["Диаметр"] = card.diameter
    if selection:
        if selection.pressure_limit:
            specs["Предел давления"] = f"{selection.pressure_limit} кПа"
        if selection.posts:
            specs["Количество постов"] = selection.posts
        if selection.lines:
            specs["Линий подключения"] = selection.lines
    return specs


async def _submit_spu_application(
    *,
    fullname: str,
    contact: str,
    comment: str,
    equipment_name: str,
    specifications: Dict[str, str],
    equipment_key: Optional[str] = None,
    source: Optional[str] = None,
    selection: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    fullname_clean = fullname.strip()
    contact_clean = contact.strip()
    comment_clean = (comment or "").strip()
    if not fullname_clean or not contact_clean:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Укажите ФИО и контакт (email или телефон).",
            },
        )
    if not equipment_name.strip():
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Не указано название установки."},
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir = Path("received_data/spu_requests")
    upload_dir.mkdir(parents=True, exist_ok=True)

    request_data: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "equipment_type": "spu",
        "equipment_name": equipment_name.strip(),
        "equipment_key": equipment_key,
        "specifications": specifications,
        "fullname": fullname_clean,
        "contact": contact_clean,
        "comment": comment_clean,
    }
    if source:
        request_data["source"] = source.strip()
    if selection is not None:
        request_data["selection"] = selection

    json_file = upload_dir / f"spu_request_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(request_data, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Заявка СПУ сохранена: {json_file}")

    email_sent = False
    email_error: Optional[str] = None

    try:
        from email_config import (
            SEND_EMAIL,
            SMTP_SERVER,
            SMTP_PORT,
            SENDER_EMAIL,
            SENDER_PASSWORD,
            RECEIVER_EMAIL,
            CC_EMAILS,
            EQUIPMENT_EMAIL_ROUTES,
        )

        if SEND_EMAIL:
            route = EQUIPMENT_EMAIL_ROUTES.get("spu") or EQUIPMENT_EMAIL_ROUTES.get(
                "verification", {}
            )
            to_email = route.get("to", RECEIVER_EMAIL)
            cc_emails = route.get("cc", CC_EMAILS)

            msg = MIMEMultipart()
            msg["From"] = SENDER_EMAIL
            msg["To"] = to_email
            if cc_emails:
                msg["Cc"] = ", ".join(cc_emails)
            msg["Subject"] = f"🔧 Заявка на поверочную установку СПУ от {fullname_clean}"

            specs_text = "\n".join(
                f"  • {k}: {v}" for k, v in specifications.items()
            )
            source_line = f"\nИсточник: {source}" if source else ""
            body = f"""
Новая заявка на поверочную установку СПУ!

══════════════════════════════════════════
📋 ДАННЫЕ УСТАНОВКИ
══════════════════════════════════════════
Название: {equipment_name.strip()}
{source_line}

Характеристики:
{specs_text}

══════════════════════════════════════════
👤 КОНТАКТНЫЕ ДАННЫЕ
══════════════════════════════════════════
ФИО: {fullname_clean}
Контакт: {contact_clean}

Комментарий: {comment_clean if comment_clean else 'Не указан'}

══════════════════════════════════════════
⏰ Время заявки: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
══════════════════════════════════════════

---
Сообщение сформировано автоматически системой подбора оборудования
Турбулентность-Дон | www.turbo-don.ru
"""
            msg.attach(MIMEText(body.strip(), "plain", "utf-8"))

            recipients = [to_email] + (cc_emails if cc_emails else [])
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg, to_addrs=recipients)
            else:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg, to_addrs=recipients)
            email_sent = True
            logger.info(f"✅ Email (СПУ) отправлен на {to_email}")

    except ImportError:
        logger.warning("⚠️ email_config недоступен. Email не отправлен.")
        email_error = "Конфигурация email не настроена"
    except Exception as email_ex:
        logger.error(f"❌ Ошибка отправки email (СПУ): {email_ex}")
        email_error = str(email_ex)

    response_message = "Заявка успешно принята и сохранена"
    if email_sent:
        response_message += ". Email отправлен."
    elif email_error:
        response_message += f". Email не отправлен: {email_error}"

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "message": response_message,
            "request_id": timestamp,
            "saved_json": str(json_file),
            "equipment_name": equipment_name.strip(),
            "equipment_key": equipment_key,
            "email_sent": email_sent,
        },
    )


async def _handle_spu_application_body(
    body: SpuApplicationRequestJson,
    request: Request,
) -> JSONResponse:
    selection_dump: Optional[Dict[str, Any]] = None
    if body.selection is not None:
        card = _build_spu_card(body.selection, request)
        equipment_name = card.name
        specifications = _spu_specifications_from_card(card, body.selection)
        equipment_key = card.equipment_key
        selection_dump = body.selection.model_dump(exclude_none=True)
    else:
        equipment_name = body.equipment_name or ""
        specifications = dict(body.specifications or {})
        equipment_key = body.equipment_key

    logger.info(
        f"📋 Заявка на СПУ от {body.fullname.strip()} ({body.contact.strip()}), "
        f"установка: {equipment_name}"
    )
    return await _submit_spu_application(
        fullname=body.fullname,
        contact=body.contact,
        comment=body.comment,
        equipment_name=equipment_name,
        specifications=specifications,
        equipment_key=equipment_key,
        source=body.source,
        selection=selection_dump,
    )


@app.get("/api/submit-spu-application", tags=["api"])
async def api_submit_spu_application_discovery():
    """Подсказка для POST: заявка на подбор поверочных установок СПУ."""
    return {
        "status": "ok",
        "message": "Отправьте POST application/json. Сначала можно подобрать карточку: POST /api/spu/card",
        "path": "/api/submit-spu-application",
        "alias_post": "/api/submit-spu-request",
        "storage_dir": "received_data/spu_requests/",
        "required_fields": ["fullname", "contact"],
        "payload_modes": {
            "selection": "параметры подбора (как POST /api/spu/card) — сервер сам соберёт название и характеристики",
            "manual": "equipment_name + specifications (как отправляет сайт после подбора)",
        },
        "example_with_selection": {
            "fullname": "Иванов Иван Иванович",
            "contact": "+7 (999) 123-45-67",
            "comment": "Нужен расчёт и КП",
            "source": "external-bot",
            "selection": {
                "meter_type": "industrial",
                "installation_type": "stationary",
                "modification": "nozzles",
                "diameter": 15,
                "accuracy": "0.2",
            },
        },
        "example_manual": {
            "fullname": "Иванов Иван Иванович",
            "contact": "buyer@example.com",
            "equipment_name": "СПУ-7 — Стационарная поверочная установка",
            "equipment_key": "spu7",
            "specifications": {
                "Тип": "Стационарная",
                "Счётчики": "Бытовые и промышленные",
                "Модификация": "Сопла",
                "Диапазон расходов": "0,016 — 1600 м³/ч",
                "Диаметр": "Ду15 мм",
                "Погрешность": "±0,2%",
            },
        },
        "spu_card_examples": "/api/spu/card (GET — подсказка по полям подбора)",
    }


@app.post("/api/submit-spu-application", tags=["api"])
async def submit_spu_application(body: SpuApplicationRequestJson, request: Request):
    """
    Заявка на поверочную установку СПУ для внешних проектов.
    Передайте `selection` (подбор) или готовые `equipment_name` + `specifications` (как на сайте).
    """
    try:
        return await _handle_spu_application_body(body, request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка submit-spu-application: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"},
        )


@app.post("/api/submit-spu-request", tags=["api"])
async def submit_spu_request(request: Request):
    """Заявка на СПУ с сайта (JSON). Алиас по смыслу — POST /api/submit-spu-application."""
    try:
        data = await request.json()
        body = SpuApplicationRequestJson.model_validate(
            {
                "fullname": data.get("fullname", ""),
                "contact": data.get("contact", ""),
                "comment": data.get("comment", ""),
                "source": data.get("source"),
                "equipment_name": data.get("equipment_name"),
                "specifications": data.get("specifications"),
                "equipment_key": data.get("equipment_key"),
                "selection": data.get("selection"),
            }
        )
        return await _handle_spu_application_body(body, request)
    except ValidationError as ve:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Ошибка валидации JSON", "details": ve.errors()},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке заявки на СПУ: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"},
        )


@app.post("/api/submit-verification-liquid-request")
async def submit_verification_liquid_request(
    fullname: str = Form(...),
    contact: str = Form(...),
    comment: str = Form(""),
    tz_file: Optional[UploadFile] = File(None),
):
    """Заявка на поверочные установки (жидкость): ПУРС и др. Шлёт файл ТЗ почтой опционально."""
    try:
        logger.info(f"📋 Получена заявка (поверка, жидкость) от {fullname.strip()} ({contact.strip()})")
        return await _submit_simple_contact_request(
            equipment_type="verification-liquid",
            equipment_name="Установка поверочная водопроливная ПУРС (заявка, жидкость)",
            storage_subdir="received_data/verification_liquid_requests",
            json_filename_prefix="verification_liquid",
            email_subject=f"💧 Заявка: поверочные установки (жидкость) от {fullname.strip()}",
            email_route_key="verification-liquid",
            fullname=fullname,
            contact=contact,
            comment=comment,
            tz_file=tz_file,
        )
    except Exception as e:
        logger.error(f"Ошибка submit-verification-liquid-request: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"},
        )


@app.get("/api/submit-household-gas-request", tags=["api"])
async def api_submit_household_gas_discovery():
    """Подсказка для POST: заявка на бытовые счётчики газа (СГ Гранд) с другого проекта."""
    return {
        "status": "ok",
        "message": "Отправьте POST multipart/form-data или application/json.",
        "path": "/api/submit-household-gas-request",
        "alias_post": "/api/submit-household-request",
        "storage_dir": "received_data/household_gas_requests/",
        "multipart_fields": {
            "fullname": "обязательно",
            "contact": "обязательно — email или телефон",
            "comment": "необязательно",
            "tz_file": "необязательно, до 10 МБ (pdf, doc, docx, txt, zip, rar)",
            "organization": "необязательно",
            "position": "необязательно",
            "phone": "необязательно",
            "email": "необязательно",
            "selected_items": "необязательно, JSON-строка: [{\"name\":\"...\",\"price\":1800,\"quantity\":1}]",
            "source": "необязательно, метка внешней системы",
        },
        "json_example": {
            "fullname": "Иванов Иван Иванович",
            "contact": "+7 (999) 123-45-67",
            "comment": "Нужна поставка 10 шт.",
            "selected_items": [
                {"name": 'Счётчик газа Гранд 1.6 1/2" РОССИЯ', "price": 1800, "quantity": 10}
            ],
            "source": "external-bot",
        },
    }


@app.post("/api/submit-household-gas-request", tags=["api"])
@app.post("/api/submit-household-request", tags=["api"], include_in_schema=False)
async def submit_household_gas_request(request: Request):
    """
    Заявка на бытовые счётчики газа (как модалка на главной странице).
    multipart/form-data — с опциональным файлом ТЗ; application/json — без файла.
    """
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        extra: Dict[str, Any] = {}
        tz_file: Optional[UploadFile] = None

        if "application/json" in content_type:
            raw = await request.json()
            body = HouseholdGasMeterRequestJson.model_validate(raw)
            fullname = body.fullname
            contact = body.contact
            comment = body.comment
            if body.organization:
                extra["organization"] = body.organization
            if body.position:
                extra["position"] = body.position
            if body.phone:
                extra["phone"] = body.phone
            if body.email:
                extra["email"] = body.email
            if body.source:
                extra["source"] = body.source
            if body.selected_items:
                extra["selected_items"] = [i.model_dump() for i in body.selected_items]
        else:
            form = await request.form()
            fullname = str(form.get("fullname") or "")
            contact = str(form.get("contact") or "")
            comment = str(form.get("comment") or "")
            for key in ("organization", "position", "phone", "email", "source"):
                val = form.get(key)
                if val is not None and str(val).strip():
                    extra[key] = str(val).strip()
            raw_items = form.get("selected_items")
            if raw_items is not None and str(raw_items).strip():
                try:
                    parsed = json.loads(str(raw_items))
                    if isinstance(parsed, list):
                        extra["selected_items"] = parsed
                except json.JSONDecodeError:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "status": "error",
                            "message": "Поле selected_items должно быть JSON-массивом.",
                        },
                    )
            raw_file = form.get("tz_file")
            if isinstance(raw_file, UploadFile) and raw_file.filename:
                tz_file = raw_file

        logger.info(
            f"📋 Заявка (бытовые счётчики газа) от {fullname.strip()} ({contact.strip()})"
        )
        return await _submit_simple_contact_request(
            equipment_type="household-gas",
            equipment_name="Бытовые счётчики газа (СГ Гранд)",
            storage_subdir="received_data/household_gas_requests",
            json_filename_prefix="household_gas",
            email_subject=f"🏠 Заявка: бытовые счётчики газа от {fullname.strip()}",
            email_route_key="household",
            fullname=fullname,
            contact=contact,
            comment=comment,
            tz_file=tz_file,
            extra_data=extra or None,
        )
    except ValidationError as ve:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Ошибка валидации JSON", "details": ve.errors()},
        )
    except Exception as e:
        logger.error(f"Ошибка submit-household-gas-request: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"},
        )


@app.post("/api/submit-ps-request")
async def submit_ps_request(request: Request):
    """Обработка заявки на датчики давления с отправкой на email"""
    try:
        data = await request.json()
        
        sensors = data.get('sensors', [])
        characteristics = data.get('characteristics', {})
        contact_info = data.get('contact_info', {})
        
        # Генерируем уникальный ID заявки
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"📧 Получена заявка на датчики давления: {sensors}")
        
        # Формируем текст для email
        email_body = f"""
Новая заявка на датчики давления Turbo Flow PS

=== КОНТАКТНАЯ ИНФОРМАЦИЯ ===
ФИО: {contact_info.get('name', 'Не указано')}
Контакт: {contact_info.get('contact', 'Не указано')}
Комментарий: {contact_info.get('comment', 'Нет')}

=== ПОДОБРАННЫЕ ДАТЧИКИ ===
{chr(10).join(['• ' + s for s in sensors])}

=== ХАРАКТЕРИСТИКИ ===
Тип преобразователя: {characteristics.get('pressureType', 'Не указано')}
Макс. давление: {characteristics.get('maxPressure', 'Не указано')} кПа
Точность: ±{characteristics.get('accuracy', 'Не указано')}%
Взрывозащита: {characteristics.get('explosionProtection', 'Не указано')}
Температура: {characteristics.get('temperatureRange', 'Не указано')}
Питание: {characteristics.get('powerType', 'Не указано')}
Индикатор: {characteristics.get('indicator', 'Не указано')}
Выход. сигнал: {characteristics.get('outputSignal', 'Не указано')}
Среда: {characteristics.get('measuredMedium', 'Не указано')}

---
ID заявки: PS-{timestamp}
Дата: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
"""
        
        # Сохраняем заявку в файл
        requests_dir = Path("requests/pressure_sensors")
        requests_dir.mkdir(parents=True, exist_ok=True)
        
        request_file = requests_dir / f"PS_{timestamp}.json"
        with open(request_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": timestamp,
                "sensors": sensors,
                "characteristics": characteristics,
                "contact_info": contact_info
            }, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Заявка сохранена: {request_file}")
        
        # Отправляем email
        email_sent = False
        email_error = None
        
        try:
            from email_config import (
                SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD,
                ENABLE_EMAIL, RECEIVER_EMAIL,
            )
            
            RECIPIENT_EMAIL = RECEIVER_EMAIL
            
            if ENABLE_EMAIL:
                msg = MIMEMultipart()
                msg['From'] = SENDER_EMAIL
                msg['To'] = RECIPIENT_EMAIL
                msg['Subject'] = f"Заявка на датчики давления PS-{timestamp}"
                msg.attach(MIMEText(email_body, 'plain', 'utf-8'))
                
                if SMTP_PORT == 465:
                    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                        server.starttls()
                        server.login(SENDER_EMAIL, SENDER_PASSWORD)
                        server.send_message(msg)
                
                email_sent = True
                logger.info(f"✅ Email успешно отправлен на {RECIPIENT_EMAIL}")
            else:
                logger.info("⚠️ Отправка email отключена в конфигурации")
                
        except ImportError:
            logger.warning("⚠️ Файл email_config.py не найден. Email не отправлен.")
            email_error = "Конфигурация email не настроена"
        except Exception as email_ex:
            logger.error(f"❌ Ошибка отправки email: {str(email_ex)}")
            email_error = str(email_ex)
        
        response_message = "Заявка успешно принята и сохранена"
        if email_sent:
            response_message += ". Email отправлен."
        elif email_error:
            response_message += f". Email не отправлен: {email_error}"
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": response_message,
                "request_id": f"PS-{timestamp}",
                "email_sent": email_sent
            }
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке заявки на датчики давления: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Ошибка сервера: {str(e)}"
            }
        )


# ===== API ДЛЯ ВЕРИФИКАЦИИ EMAIL =====

@app.post("/api/send-verification-code")
async def send_verification_code(request: Request):
    """Отправка кода верификации на email"""
    try:
        data = await request.json()
        email = data.get("email", "").strip().lower()
        
        if not email:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Email не указан"}
            )
        
        # Простая валидация email
        import re
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Некорректный email"}
            )
        
        # Генерируем 6-значный код
        code = str(random.randint(100000, 999999))
        expires = datetime.now().timestamp() + VERIFICATION_CODE_TTL
        
        # Сохраняем код (файл, доступен всем workers)
        _vc_purge()
        _vc_set(email, code, expires)
        
        # Отправляем email с кодом
        try:
            from email_config import (
                SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD, SEND_EMAIL,
                RECEIVER_EMAIL,
            )
            
            if not SEND_EMAIL:
                logger.info(f"Отправка email отключена. Код для {email}: {code}")
                return JSONResponse(
                    status_code=200,
                    content={"status": "success", "message": "Код отправлен (тестовый режим)", "debug_code": code}
                )
            
            msg = MIMEMultipart()
            msg['From'] = SENDER_EMAIL
            msg['To'] = email
            msg['Subject'] = "Код подтверждения - Turbo Flow"
            
            body = f"""
Ваш код подтверждения: {code}

Код действителен 5 минут.

Если вы не запрашивали код, просто проигнорируйте это письмо.

---
Turbo Flow - Система подбора оборудования
"""
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg)
            
            logger.info(f"✅ Код верификации отправлен на {email}")
            
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Код отправлен на вашу почту"}
            )
            
        except ImportError:
            logger.warning("email_config.py не найден")
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Код отправлен (тестовый режим)", "debug_code": code}
            )
            
    except Exception as e:
        logger.error(f"Ошибка отправки кода верификации: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"}
        )


@app.post("/api/verify-code")
async def verify_code(request: Request):
    """Проверка кода верификации"""
    try:
        data = await request.json()
        email = data.get("email", "").strip().lower()
        code = data.get("code", "").strip()
        
        if not email or not code:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Email и код обязательны"}
            )
        
        _vc_purge()
        stored = _vc_get(email)
        if not stored:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Сначала запросите код"}
            )
        
        # Проверяем срок действия
        if datetime.now().timestamp() > stored["expires"]:
            _vc_delete(email)
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Код истёк. Запросите новый"}
            )
        
        # Проверяем код
        if stored["code"] != code:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Неверный код"}
            )
        
        # Код верный - помечаем как подтверждённый
        _vc_mark_verified(email)
        logger.info(f"✅ Email {email} подтверждён")
        
        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": "Email подтверждён", "verified": True}
        )
        
    except Exception as e:
        logger.error(f"Ошибка проверки кода: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"}
        )


@app.post("/api/send-price-inquiry")
async def send_price_inquiry(request: Request):
    """Отправка уведомления о запросе цены на email"""
    try:
        data = await request.json()
        phone = data.get("phone", "")
        email = data.get("email", "")
        equipment_name = data.get("equipment_name", "Расходомер")
        price = data.get("price", "по запросу")
        
        if not phone or not email:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Не указаны контактные данные"}
            )
        
        # Отправляем email
        try:
            from email_config import (
                SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD, SEND_EMAIL,
                RECEIVER_EMAIL,
            )
            
            if not SEND_EMAIL:
                logger.info(f"Отправка email отключена. Запрос цены: {equipment_name}, {phone}, {email}")
                return JSONResponse(
                    status_code=200,
                    content={"status": "success", "message": "Уведомление отправлено (тестовый режим)"}
                )
            
            # Email получателя
            RECIPIENT_EMAIL = RECEIVER_EMAIL
            
            msg = MIMEMultipart()
            msg['From'] = SENDER_EMAIL
            msg['To'] = RECIPIENT_EMAIL
            msg['Subject'] = f"Запрос цены: {equipment_name}"
            
            body = f"""
Пользователь узнал цену на расходомер

═══════════════════════════════════════
ИНФОРМАЦИЯ О РАСХОДОМЕРЕ
═══════════════════════════════════════
{equipment_name}

Предварительная стоимость: {price}

═══════════════════════════════════════
КОНТАКТНЫЕ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ
═══════════════════════════════════════
Телефон: {phone}
E-mail:  {email}

═══════════════════════════════════════

Дата и время запроса: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}

---
Автоматическое уведомление из системы подбора оборудования Turbo Flow
"""
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg)
            
            logger.info(f"✅ Уведомление о запросе цены отправлено на {RECIPIENT_EMAIL}")
            
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Уведомление отправлено"}
            )
            
        except ImportError:
            logger.warning("email_config.py не найден")
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Уведомление отправлено (тестовый режим)"}
            )
            
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления о цене: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"}
        )


@app.post("/api/send-tkp-request")
async def send_tkp_request(request: Request):
    """Отправка запроса на ТКП на email"""
    try:
        data = await request.json()
        phone = data.get("phone", "")
        email = data.get("email", "")
        equipment_name = data.get("equipment_name", "Расходомер")
        price = data.get("price", "по запросу")
        accessories = data.get("accessories", [])
        
        try:
            from email_config import (
                SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD, SEND_EMAIL,
                RECEIVER_EMAIL,
            )
            
            if not SEND_EMAIL:
                logger.info(f"Отправка email отключена. Запрос ТКП: {equipment_name}, {phone}, {email}, комплектующие: {accessories}")
                return JSONResponse(
                    status_code=200,
                    content={"status": "success", "message": "Запрос ТКП отправлен (тестовый режим)"}
                )
            
            RECIPIENT_EMAIL = RECEIVER_EMAIL
            
            accessories_text = ""
            if accessories:
                accessories_text = f"""
═══════════════════════════════════════
ДОПОЛНИТЕЛЬНЫЕ КОМПЛЕКТУЮЩИЕ
═══════════════════════════════════════
{chr(10).join('• ' + a for a in accessories)}
"""
            else:
                accessories_text = """
═══════════════════════════════════════
ДОПОЛНИТЕЛЬНЫЕ КОМПЛЕКТУЮЩИЕ
═══════════════════════════════════════
Не выбраны
"""
            
            msg = MIMEMultipart()
            msg['From'] = SENDER_EMAIL
            msg['To'] = RECIPIENT_EMAIL
            msg['Subject'] = f"Запрос ТКП: {equipment_name}"
            
            body = f"""
Пользователь запросил технико-коммерческое предложение (ТКП)

═══════════════════════════════════════
ИНФОРМАЦИЯ О РАСХОДОМЕРЕ
═══════════════════════════════════════
{equipment_name}

Предварительная стоимость: {price}
{accessories_text}
═══════════════════════════════════════
КОНТАКТНЫЕ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ
═══════════════════════════════════════
Телефон: {phone}
E-mail:  {email}

═══════════════════════════════════════

Дата и время запроса: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}

Необходимо подготовить и отправить ТКП на указанный e-mail.

---
Автоматическое уведомление из системы подбора оборудования Turbo Flow
"""
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SENDER_EMAIL, SENDER_PASSWORD)
                    server.send_message(msg)
            
            logger.info(f"✅ Запрос ТКП отправлен на {RECIPIENT_EMAIL}")
            
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Запрос ТКП отправлен"}
            )
            
        except ImportError:
            logger.warning("email_config.py не найден")
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "Запрос ТКП отправлен (тестовый режим)"}
            )
            
    except Exception as e:
        logger.error(f"Ошибка отправки запроса ТКП: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Ошибка сервера: {str(e)}"}
        )


def calculate_equipment_parameters(equipment: Dict[str, Any]) -> Dict[str, Any]:
    """Расчет дополнительных параметров оборудования"""
    specs = equipment.get("specs", {})
    params = equipment.get("params", {})
    
    calculated = {
        "flow_formula": params.get("flowFormula", ""),
        "pressure_loss_formula": params.get("pressureLossFormula", ""),
        "recommended_straight_sections": {
            "upstream": "10D",
            "downstream": "5D"
        },
        "installation_requirements": [
            "Обеспечить прямые участки трубопровода",
            "Исключить вибрации и пульсации",
            "Обеспечить заземление"
        ]
    }
    
    # Добавляем специфичные для типа расчеты
    equipment_type = equipment.get("type", "")
    if "ultrasonic" in equipment_type.lower():
        calculated["measurement_principle"] = "Ультразвуковой метод измерения времени прохождения"
        calculated["accuracy_factors"] = [
            "Качество ультразвукового сигнала",
            "Профиль скорости потока",
            "Температура среды"
        ]
    elif "vortex" in equipment_type.lower():
        calculated["measurement_principle"] = "Измерение частоты вихрей Кармана"
        calculated["accuracy_factors"] = [
            "Стабильность потока",
            "Число Рейнольдса",
            "Вибрации трубопровода"
        ]
    
    return calculated

# ===== ФУНКЦИИ И ЭНДПОИНТЫ ДЛЯ РАБОТЫ С 1С =====

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Проверка токена авторизации"""
    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Неверный токен авторизации"
        )
    return credentials.credentials

_bearer_optional = HTTPBearer(auto_error=False)

def _1c_token_check(
    credentials: Optional[HTTPAuthorizationCredentials],
    body_bearer: Optional[str],
) -> str:
    """Возвращает ok | missing | invalid."""
    if credentials and credentials.credentials == API_TOKEN:
        return "ok"
    raw = (body_bearer or "").strip()
    if not raw:
        return "missing"
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if raw == API_TOKEN:
        return "ok"
    return "invalid"

async def require_1c_api_auth(
    request_data: APIRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_optional),
) -> None:
    """HTTP Bearer в заголовке ИЛИ поле Authorization в JSON-теле (как в Postman/1С/браузере)."""
    r = _1c_token_check(credentials, request_data.authorization)
    if r == "ok":
        return
    if r == "missing":
        raise HTTPException(status_code=401, detail="Not authenticated")
    raise HTTPException(status_code=401, detail="Неверный токен авторизации")


def _resolve_price_file_path(equipment_id: str, equipment_name: Optional[str]) -> Optional[Path]:
    """Путь к .js файлу прайса в каталоге прайсы/ или None."""
    eid = (equipment_id or "").strip().lower()
    name_l = (equipment_name or "").lower()
    fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get(eid)
    if not fn and name_l:
        if "ufg-f-v" in name_l or "ufg f v" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("ufg2")
        elif "ufg-f-c" in name_l or "ufg f c" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("ufgfc1")
        elif "tfg-s" in name_l and "tfg-h" not in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("tfgs1")
        elif "tfg-h" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("tfgh1")
        elif "ufg-h" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("ufgh1")
        elif "gfg" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("gfg2")
        elif "ufl" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("ufl1")
        elif "cfm" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("cfm1")
        elif "udm" in name_l or "плотномер" in name_l:
            fn = EQUIPMENT_ID_TO_PRICE_FILENAME.get("udm1")
    if not fn:
        return None
    p = PRAISES_DIR / fn
    return p if p.is_file() else None


async def require_1c_token_for_price_body(
    equipment: EquipmentCardForPrice,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_optional),
) -> None:
    r = _1c_token_check(credentials, equipment.authorization)
    if r == "ok":
        return
    if r == "missing":
        raise HTTPException(status_code=401, detail="Not authenticated")
    raise HTTPException(status_code=401, detail="Неверный токен авторизации")


@app.post("/api/1c/price-file")
async def download_1c_price_file(
    equipment: EquipmentCardForPrice,
    _auth: None = Depends(require_1c_token_for_price_body),
):
    """Возвращает файл прайса (данные в формате .js из каталога прайсы), по id оборудования."""
    path = _resolve_price_file_path(equipment.id, equipment.name)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Прайс для данного id не найден. Проверьте id и наличие файла в каталоге прайсы.",
        )
    return FileResponse(
        path=path,
        media_type="text/javascript; charset=utf-8",
        filename=path.name,
    )


def _equipment_params_from_1c_data(data: Dict[str, Any]) -> EquipmentParams:
    """Собирает EquipmentParams из объекта data для 1С: только известные поля, срез лишнего."""
    if not data:
        return EquipmentParams(medium="gas")
    allowed = set(EquipmentParams.model_fields.keys())
    payload: Dict[str, Any] = {}
    for k, v in data.items():
        if k not in allowed:
            continue
        if v is None or v == "":
            continue
        # 1С/JSON часто шлют числа; в модели поля str (запятые в UI). Pydantic v2 str не принимает int/float.
        if isinstance(v, (int, float)):
            v = str(v)
        elif isinstance(v, bool):
            v = "true" if v else "false"
        payload[k] = v
    if not payload.get("medium"):
        payload["medium"] = "gas"
    return EquipmentParams.model_validate(payload)


def _equipment_static_image_url(raw_image: Optional[Any]) -> Optional[str]:
    """
    Относительный URL для <img src>: /static/<путь из data.json>.
    Если положить такую же структуру static/ в другой проект и раздавать /static — картинка откроется с домена этого фронта.

    Пример data.json «equipment/Turbo_Flow_CFM.png» → «/static/equipment/Turbo_Flow_CFM.png» (файл: static/equipment/...).

    Если в JSON уже полный http(s)-URL — возвращается без изменений.
    """
    if raw_image is None:
        return None
    s = str(raw_image).strip()
    if not s:
        return None
    if s.startswith(("http://", "https://")):
        return s
    p = s.replace("\\", "/").lstrip("/")
    segments = [quote(part, safe="") for part in p.split("/") if part]
    if not segments:
        return None
    return "/static/" + "/".join(segments)


# Основной эндпоинт для принятия данных от 1С
@app.post("/api/1c/data", response_model=APIResponse)
async def receive_1c_data(
    request_data: APIRequest,
    _auth: None = Depends(require_1c_api_auth),
):
    """Принятие данных от 1С"""
    try:
        logger.info(f"Получен запрос типа: {request_data.type}")
        equipment: Optional[List[Dict[str, Any]]] = None
        total_count: Optional[int] = None
        # Обработка данных в зависимости от типа
        if request_data.type == "login":
            await process_login(request_data.data)
        elif request_data.type == "equipment_params":
            try:
                search_params = _equipment_params_from_1c_data(request_data.data)
            except ValidationError as e:
                raise HTTPException(status_code=422, detail=e.errors()) from e
            matches = find_matching_equipment(search_params)
            equipment = []
            for eq in matches:
                row = dict(eq)
                row["recommended_diameter"] = get_recommended_diameter_for_equipment(
                    eq, search_params
                )
                img = _equipment_static_image_url(row.get("image"))
                if img:
                    row["image_url"] = img
                    row["image_path"] = img
                equipment.append(row)
            total_count = len(equipment)
        else:
            logger.warning(
                "Тип %s зарезервирован; подбор оборудования не выполнялся",
                request_data.type,
            )
        # Сохранение данных в файл (опционально)
        await save_data_to_file(request_data)
        # Формирование ответа
        response = APIResponse(
            status="success",
            message="Данные успешно получены и обработаны",
            received_at=datetime.now().isoformat(),
            data_type=request_data.type,
            equipment=equipment,
            total_count=total_count,
        )
        logger.info(f"Данные успешно обработаны: {request_data.type}")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка обработки запроса: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")

# Функция обработки логина
async def process_login(data):
    """Обработка данных логина"""
    try:
        login_data = LoginData(**data)
        logger.info(f"Получен логин: {login_data.login}")
        
        # ЗДЕСЬ ВЫ МОЖЕТЕ ДОБАВИТЬ СВОЮ ЛОГИКУ:
        # - Сохранение в базу данных
        # - Отправка уведомлений
        # - Интеграция с CRM системой
        # - Любая другая обработка
        
        # Пример: сохранение в базу данных (псевдокод)
        # await save_login_to_database(login_data.login)
        
        # Пример: отправка уведомления (псевдокод)
        # await send_notification(f"Новый логин: {login_data.login}")
        
        return {"status": "success", "message": f"Логин {login_data.login} обработан"}
        
    except Exception as e:
        logger.error(f"Ошибка обработки логина: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка обработки логина")

# Функция сохранения данных в файл
async def save_data_to_file(request_data: APIRequest):
    """Сохранение данных в файл для архива"""
    try:
        # Создание папки для данных
        data_dir = Path("received_data")
        data_dir.mkdir(exist_ok=True)
        
        # Формирование имени файла с временной меткой
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{request_data.type}_{timestamp}.json"
        file_path = data_dir / filename
        
        # Сохранение данных
        with open(file_path, 'w', encoding='utf-8') as f:
            payload = request_data.model_dump(
                mode="json",
                exclude={"authorization"},
                by_alias=True,
            )
            json.dump(payload, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Данные сохранены в файл: {file_path}")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {str(e)}")

# Эндпоинт для получения последней сессии пользователя
@app.get("/download/questionnaire-template")
async def download_questionnaire_template():
    """Скачивание шаблона опросного листа для блочно-модульных изделий"""
    from fastapi.responses import FileResponse
    
    # Используем BASE_DIR для абсолютного пути
    template_path = Path(BASE_DIR) / "PURG OL.DOC"
    
    if not template_path.exists():
        logger.error(f"Файл шаблона не найден: {template_path}")
        raise HTTPException(status_code=404, detail="Файл шаблона не найден")
    
    logger.info(f"Скачивание шаблона опросного листа: {template_path}")
    
    return FileResponse(
        path=str(template_path),
        filename="Опросный_лист_ПУРГ.doc",
        media_type="application/msword",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''%D0%9E%D0%BF%D1%80%D0%BE%D1%81%D0%BD%D1%8B%D0%B9_%D0%BB%D0%B8%D1%81%D1%82_%D0%9F%D0%A3%D0%A0%D0%93.doc"
        }
    )

@app.get("/download/questionnaire/{template_name}")
async def download_questionnaire(template_name: str):
    """Скачивание опросных листов для поверочных установок"""
    from fastapi.responses import FileResponse
    
    # Мапинг допустимых имен файлов
    allowed_templates = {
        "spu3": ("OL SPU3.doc", "Опросный_лист_СПУ3.doc", "application/msword"),
        "spu5": ("OL SPU5.xlsx", "Опросный_лист_СПУ5.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "spu7": ("OL SPU7.xlsx", "Опросный_лист_СПУ7.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "purs": ("OL PURS.doc", "Опросный_лист_PURS.doc", "application/msword"),
        "purg": ("PURG OL.DOC", "Опросный_лист_ПУРГ.doc", "application/msword"),
        "ps": ("OL PS.docx", "Опросный_лист_Датчики_давления.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "gfg": ("OL GFG.docx", "Опросный_лист_GFG.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    }
    
    template_name_lower = template_name.lower()
    
    if template_name_lower not in allowed_templates:
        logger.error(f"Недопустимое имя шаблона: {template_name}")
        raise HTTPException(status_code=400, detail="Недопустимое имя шаблона")
    
    file_name, display_name, media_type = allowed_templates[template_name_lower]
    template_path = Path(BASE_DIR) / file_name
    
    if not template_path.exists():
        logger.error(f"Файл шаблона не найден: {template_path}")
        raise HTTPException(status_code=404, detail=f"Файл {file_name} не найден")
    
    logger.info(f"Скачивание опросного листа: {template_path}")
    
    return FileResponse(
        path=str(template_path),
        filename=display_name,
        media_type=media_type
    )

@app.get("/api/get-latest-session")
async def get_latest_session(request: Request):
    """Получение данных последней сессии пользователя из полученных данных от 1С"""
    try:
        # Получаем session_id из cookies
        user_session_id = request.cookies.get("session_id")
        logger.info(f"Запрос данных сессии для session_id из cookies: {user_session_id}")
        
        received_data_dir = Path("received_data")
        if not received_data_dir.exists():
            return {
                "status": "error",
                "message": "Папка с данными не найдена",
                "login": None,
                "session_id": None
            }
        
        # Ищем все файлы логинов
        login_files = list(received_data_dir.glob("login_*.json"))
        
        if not login_files:
            return {
                "status": "error", 
                "message": "Данные сессии не найдены",
                "login": None,
                "session_id": None
            }
        
        # Если есть session_id в cookies, ищем файл с соответствующим session_id
        if user_session_id:
            logger.info(f"Поиск файла логина для session_id: {user_session_id}")
            for login_file in login_files:
                try:
                    with open(login_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    
                    # Проверяем, совпадает ли session_id в файле с session_id из cookies
                    file_session_id = session_data.get('data', {}).get('session_id', '')
                    
                    if file_session_id == user_session_id:
                        # Нашли файл с нужным session_id!
                        data = session_data.get('data', {})
                        login = data.get('login', '')
                        
                        logger.info(f"✅ Найден файл логина для session_id {user_session_id}: логин={login}")
                        
                        return {
                            "status": "success",
                            "message": "Данные сессии получены для вашего session_id",
                            "login": login,
                            "session_id": file_session_id,
                            "timestamp": session_data.get('timestamp', ''),
                            "file": login_file.name
                        }
                except Exception as file_error:
                    logger.warning(f"Ошибка чтения файла {login_file}: {file_error}")
                    continue
            
            # Если дошли сюда, значит файл с нужным session_id не найден
            logger.warning(f"⚠️ Файл логина для session_id {user_session_id} не найден")
            return {
                "status": "error",
                "message": f"Данные для вашей сессии не найдены. Возможно, вы не переходили из 1С.",
                "login": None,
                "session_id": user_session_id
            }
        
        # Если session_id нет в cookies, берём самый свежий файл (старое поведение для обратной совместимости)
        logger.warning("⚠️ Session ID отсутствует в cookies, используем последний файл логина")
        login_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        latest_file = login_files[0]
        with open(latest_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
        
        # Извлекаем данные логина и сессии
        data = session_data.get('data', {})
        login = data.get('login', '')
        session_id = data.get('session_id', '')
        
        logger.info(f"Получена последняя сессия (без привязки к session_id): логин={login}, session_id={session_id}")
        
        return {
            "status": "success",
            "message": "Данные последней сессии получены (без привязки к вашей сессии)",
            "login": login,
            "session_id": session_id,
            "timestamp": session_data.get('timestamp', ''),
            "file": latest_file.name,
            "warning": "Session ID не найден в cookies, используются данные последнего пользователя"
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения сессии: {str(e)}")
        return {
            "status": "error",
            "message": f"Ошибка получения данных сессии: {str(e)}",
            "login": None,
            "session_id": None
        }

# Тестовый эндпоинт для проверки работы 1С API
@app.get("/api/1c/test")
async def test_1c_endpoint():
    """Тестовый эндпоинт для проверки работы API"""
    return {
        "status": "success",
        "message": "1С API работает корректно",
        "timestamp": datetime.now().isoformat(),
        "endpoints": ["/api/1c/data", "/api/1c/test", "/api/get-latest-session"]
    }


# ============================================================================
# УНИВЕРСАЛЬНЫЙ ПРИЁМНИК: принимает запрос любым HTTP-методом и любого формата.
# Адреса:
#   /api/receive                       — базовый путь
#   /api/receive/любой/подпуть         — произвольные подпути
# Методы: GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD
# Форматы тела: JSON, form-urlencoded, multipart/form-data, raw text, binary
# Авторизация не требуется (если нужна — добавьте Depends(verify_token)).
# Данные логируются и сохраняются в папку received_data/.
# ============================================================================
@app.api_route(
    "/api/receive",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
@app.api_route(
    "/api/receive/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def universal_receive(request: Request, subpath: str = ""):
    """Универсальный endpoint: принимает данные любого формата любым HTTP-методом."""
    query_params = dict(request.query_params)
    headers = dict(request.headers)
    content_type = (request.headers.get("content-type") or "").lower()

    raw_body = await request.body()

    body_parsed = None
    body_error = None
    if raw_body:
        try:
            if "application/json" in content_type:
                body_parsed = json.loads(raw_body.decode("utf-8", errors="replace"))
            elif ("application/x-www-form-urlencoded" in content_type
                  or "multipart/form-data" in content_type):
                form = await request.form()
                body_parsed = {
                    k: (v if isinstance(v, str) else f"<file: {getattr(v, 'filename', 'unnamed')}>")
                    for k, v in form.multi_items()
                }
            else:
                try:
                    body_parsed = raw_body.decode("utf-8")
                except UnicodeDecodeError:
                    body_parsed = f"<binary {len(raw_body)} bytes>"
        except Exception as e:
            body_error = str(e)
            try:
                body_parsed = raw_body.decode("utf-8", errors="replace")
            except Exception:
                body_parsed = "<undecodable binary>"

    received_entry = {
        "received_at": datetime.now().isoformat(),
        "method": request.method,
        "path": str(request.url.path),
        "subpath": subpath,
        "full_url": str(request.url),
        "client": {
            "host": request.client.host if request.client else None,
            "port": request.client.port if request.client else None,
        },
        "content_type": content_type,
        "query_params": query_params,
        "headers": headers,
        "body": body_parsed,
        "body_parse_error": body_error,
    }

    logger.info(
        f"[receive] {request.method} {request.url.path} "
        f"from={received_entry['client']['host']} "
        f"qs={len(query_params)} body_len={len(raw_body)}"
    )
    try:
        logger.info(
            "[receive] payload="
            + json.dumps(received_entry, ensure_ascii=False, default=str)[:5000]
        )
    except Exception:
        pass

    try:
        data_dir = Path("received_data")
        data_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_subpath = (subpath or "root").replace("/", "_").replace("\\", "_")[:50]
        file_path = data_dir / f"universal_{request.method}_{safe_subpath}_{timestamp}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(received_entry, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.error(f"[receive] ошибка сохранения файла: {e}")

    return JSONResponse({
        "status": "ok",
        "message": "Данные получены и сохранены",
        "received": {
            "method": request.method,
            "path": str(request.url.path),
            "subpath": subpath,
            "query_params": query_params,
            "content_type": content_type,
            "has_body": bool(raw_body),
            "body": body_parsed,
        },
    })

# Для хостинга: uvicorn.run() удален для совместимости с хостинг-провайдером
# Приложение будет запускаться через ASGI сервер хостинга
# Локально по умолчанию порт 8010 (на 8000 часто сидит Django runserver).
# Вручную: py -m uvicorn main:app --host 127.0.0.1 --port 8010

if __name__ == "__main__":
    # Локальный запуск только для разработки. Не используем uvicorn.run() в том же интерпретаторе:
    # при `python main.py` файл сначала выполняется как __main__, затем uvicorn снова импортирует
    # модуль `main`, что даёт двойную инициализацию и на части сборок приводит к 500 на GET /.
    # Запускаем подпроцесс `python -m uvicorn main:app` — один корректный импорт, как при ручном вызове.
    import sys
    import subprocess
    
    host = "0.0.0.0"
    port = 8010
    if "--host" in sys.argv:
        i = sys.argv.index("--host")
        if i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        if i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    use_reload = "--reload" in sys.argv
    argv = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if use_reload:
        argv.append("--reload")
    print("🚀 Запуск в режиме разработки...")
    print(f"📍 Локальный доступ: http://127.0.0.1:{port}")
    print(f"🌐 Сетевой доступ: http://{host}:{port}")
    if use_reload:
        print("🔄 Reload: включён (--reload)")
    print("⚠️  Для production используйте passenger_wsgi.py")
    print(
        f"📋 Проверка API: GET http://127.0.0.1:{port}/api/estimate-price  |  "
        f"GET http://127.0.0.1:{port}/api/tkp-accessories  |  "
        f"GET http://127.0.0.1:{port}/api/tkp-pdf  |  /docs"
    )
    raise SystemExit(subprocess.call(argv, cwd=BASE_DIR))