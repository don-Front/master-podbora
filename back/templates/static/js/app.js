// Приложение подбора оборудования
class EquipmentSelector {
    constructor() {
        this.currentStep = 1;
        this.maxSteps = 4;
        this.selectedData = {
            medium: null,
            application: null,
            gasType: null,
            params: {}
        };
        this.init();
    }

    init() {
        this.loadParamsFromUrl();
        this.bindEvents();
        this.showStep(1);
        this.updateSteps();
    }

    loadParamsFromUrl() {
        const urlParams = new URLSearchParams(window.location.search);
        this.selectedData.medium = urlParams.get('medium');
        this.selectedData.application = urlParams.get('application');
        this.selectedData.gasType = urlParams.get('gas_type');
        
        console.log('Загружены параметры из URL:', this.selectedData);
    }

    bindEvents() {
        // Обработчики для карточек опций
        document.addEventListener('click', (e) => {
            if (e.target.closest('.option-card')) {
                this.handleOptionSelect(e.target.closest('.option-card'));
            }
        });

        // Обработчики для кнопок
        document.addEventListener('click', (e) => {
            const target = e.target.closest('button');
            if (!target) return;

            const buttonId = target.id;
            switch (buttonId) {
                case 'search-btn':
                case 'calculate-btn':
                    this.searchEquipment();
                    break;
                case 'back-btn':
                    this.prevStep();
                    break;
                case 'new-search-btn':
                    this.reset();
                    break;
                case 'error-ok-btn':
                    this.hideModal();
                    break;
            }
        });

        // Обработчики для полей ввода
        document.querySelectorAll('input, select').forEach(input => {
            input.addEventListener('input', () => this.clearFieldError(input));
            input.addEventListener('change', () => this.clearFieldError(input));
        });

        // Обработчики для условий измерения газа
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('condition-btn')) {
                // Убрать активный класс с других кнопок
                e.target.parentNode.querySelectorAll('.condition-btn').forEach(btn => {
                    btn.classList.remove('active');
                });
                // Добавить активный класс к выбранной кнопке
                e.target.classList.add('active');
            }
        });
    }

    showStep(step) {
        // Скрыть все шаги
        document.querySelectorAll('.step-content').forEach(content => {
            content.style.display = 'none';
        });

        // Показать текущий шаг
        let currentContent;
        switch(step) {
            case 1:
                currentContent = document.getElementById('medium-selection');
                break;
            case 2:
                currentContent = document.getElementById('application-selection');
                break;
            case 3:
                currentContent = document.getElementById('gas-type-selection');
                break;
            case 4:
                currentContent = document.getElementById('params-selection');
                break;
        }
        
        if (currentContent) {
            currentContent.style.display = 'block';
        }

        this.currentStep = step;
        this.updateButtons();
    }

    updateSteps() {
        document.querySelectorAll('.step').forEach((step, index) => {
            const stepNumber = index + 1;
            step.classList.remove('active', 'completed');
            
            if (stepNumber < this.currentStep) {
                step.classList.add('completed');
            } else if (stepNumber === this.currentStep) {
                step.classList.add('active');
            }
        });
    }

    updateButtons() {
        const backBtn = document.getElementById('back-btn');
        const searchBtn = document.getElementById('search-btn');

        // Кнопка "Назад"
        if (backBtn) {
            backBtn.style.display = this.currentStep > 1 ? 'inline-flex' : 'none';
        }

        // Кнопка "Подобрать оборудование"
        if (searchBtn) {
            searchBtn.style.display = this.currentStep === this.maxSteps ? 'inline-flex' : 'none';
        }
    }

    handleOptionSelect(card) {
        const step = this.currentStep;
        const value = card.dataset.value;
        const stepContainer = card.closest('.step-content');

        // Убрать выделение с других карточек в этом шаге
        stepContainer.querySelectorAll('.option-card').forEach(c => {
            c.classList.remove('selected');
        });

        // Выделить выбранную карточку
        card.classList.add('selected');

        // Сохранить выбор и перейти к следующему шагу
        switch (step) {
            case 1:
                this.selectedData.medium = value;
                if (value === 'gas') {
                    setTimeout(() => this.showStep(2), 500);
                } else if (value === 'liquid') {
                    // Для жидкости пропускаем шаги 2 и 3, сразу к параметрам
                    this.selectedData.application = 'industrial';
                    this.selectedData.gasType = null;
                    setTimeout(() => this.showStep(4), 500);
                }
                break;
            case 2:
                this.selectedData.application = value;
                if (value === 'industrial') {
                    setTimeout(() => this.showStep(3), 500);
                } else {
                    // Для коммунально-бытового сразу к параметрам
                    this.selectedData.gasType = 'natural';
                    setTimeout(() => this.showStep(4), 500);
                }
                break;
            case 3:
                this.selectedData.gasType = value;
                setTimeout(() => this.showStep(4), 500);
                break;
        }
    }

    updateParamsForm() {
        const liquidFlowGroup = document.getElementById('liquidFlowGroup');
        const gasConditionsGroup = document.getElementById('gasConditionsGroup');
        const densityGroup = document.getElementById('densityGroup');

        // Показать/скрыть поля в зависимости от выбранной среды
        if (this.selectedData.medium === 'liquid') {
            liquidFlowGroup.style.display = 'block';
            gasConditionsGroup.style.display = 'none';
            densityGroup.style.display = 'block';
        } else if (this.selectedData.medium === 'gas' && this.selectedData.gasType === 'natural') {
            liquidFlowGroup.style.display = 'none';
            gasConditionsGroup.style.display = 'block';
            densityGroup.style.display = 'none';
        } else {
            liquidFlowGroup.style.display = 'none';
            gasConditionsGroup.style.display = 'none';
            densityGroup.style.display = 'none';
        }
    }

    nextStep() {
        if (!this.validateCurrentStep()) {
            return;
        }

        if (this.currentStep < this.maxSteps) {
            this.showStep(this.currentStep + 1);
        }
    }

    prevStep() {
        if (this.currentStep > 1) {
            this.showStep(this.currentStep - 1);
        }
    }

    validateCurrentStep() {
        const step = this.currentStep;

        switch (step) {
            case 1:
                if (!this.selectedData.medium) {
                    this.showError('Ошибка', 'Пожалуйста, выберите измеряемую среду.');
                    return false;
                }
                break;
            case 2:
                if (!this.selectedData.application) {
                    this.showError('Ошибка', 'Пожалуйста, выберите сферу применения.');
                    return false;
                }
                break;
            case 3:
                if (this.selectedData.medium === 'gas' && !this.selectedData.gasType) {
                    this.showError('Ошибка', 'Пожалуйста, выберите тип газа.');
                    return false;
                }
                break;
        }
        return true;
    }

    validateParams() {
        const errors = [];
        const params = {};

        // Получить все значения из формы
        const inputs = document.querySelectorAll('.params-form input, .params-form select');
        inputs.forEach(input => {
            if (input.value.trim()) {
                params[input.name] = input.value.trim();
            }
        });

        // Получить выбранные единицы измерения из активных кнопок
        const activeFlowUnit = document.querySelector('#flow-units .unit-btn.active');
        if (activeFlowUnit) {
            params.flowUnit = activeFlowUnit.getAttribute('data-unit');
        }
        
        // Для давления и температуры используются статические единицы измерения
        params.pressureUnit = 'МПа';
        params.tempUnit = '°C';

        // Проверка обязательных полей
        const requiredFields = ['flowMin', 'flowMax'];
        requiredFields.forEach(field => {
            const input = document.querySelector(`[name="${field}"]`);
            if (!params[field]) {
                this.addFieldError(input, 'Обязательное поле');
                errors.push(`Поле "${input.previousElementSibling.textContent}" обязательно для заполнения.`);
            }
        });

        // Проверка числовых значений
        const positiveFields = [
            'flowMin', 'flowMax', 'diameter', 'pressureMin', 'pressureMax',
            'densityMin', 'densityMax', 'accuracy'
        ];
        
        const numericFields = [
            'tempMediumMin', 'tempMediumMax', 'tempAmbientMin', 'tempAmbientMax'
        ];

        // Проверка полей, которые должны быть положительными
        positiveFields.forEach(field => {
            if (params[field]) {
                const value = parseFloat(params[field]);
                const input = document.querySelector(`[name="${field}"]`);
                
                if (isNaN(value) || value < 0) {
                    this.addFieldError(input, 'Некорректное значение');
                    errors.push(`Поле "${input.previousElementSibling.textContent}" должно содержать положительное число.`);
                }
            }
        });
        
        // Проверка полей, которые могут быть отрицательными (температура)
        numericFields.forEach(field => {
            if (params[field]) {
                const value = parseFloat(params[field]);
                const input = document.querySelector(`[name="${field}"]`);
                
                if (isNaN(value)) {
                    this.addFieldError(input, 'Некорректное значение');
                    errors.push(`Поле "${input.previousElementSibling.textContent}" должно содержать число.`);
                }
            }
        });

        // Проверка логической согласованности
        const ranges = [
            { min: 'flowMin', max: 'flowMax', name: 'Расход' },
            { min: 'pressureMin', max: 'pressureMax', name: 'Давление' },
            { min: 'tempMediumMin', max: 'tempMediumMax', name: 'Температура среды' },
            { min: 'tempAmbientMin', max: 'tempAmbientMax', name: 'Температура окружающей среды' },
            { min: 'densityMin', max: 'densityMax', name: 'Плотность' }
        ];

        ranges.forEach(range => {
            const minVal = parseFloat(params[range.min]);
            const maxVal = parseFloat(params[range.max]);
            
            if (!isNaN(minVal) && !isNaN(maxVal) && minVal > maxVal) {
                const minInput = document.querySelector(`[name="${range.min}"]`);
                const maxInput = document.querySelector(`[name="${range.max}"]`);
                
                this.addFieldError(minInput, 'Мин > Макс');
                this.addFieldError(maxInput, 'Макс < Мин');
                errors.push(`${range.name}: минимальное значение не может быть больше максимального.`);
            }
        });

        if (errors.length > 0) {
            this.showError('Ошибки в параметрах', errors.join('\n'));
            return false;
        }

        this.selectedData.params = params;
        return true;
    }

    addFieldError(input, message) {
        input.classList.add('error');
        
        // Удалить существующее сообщение об ошибке
        const existingError = input.parentNode.querySelector('.error-message');
        if (existingError) {
            existingError.remove();
        }

        // Добавить новое сообщение об ошибке
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = message;
        input.parentNode.appendChild(errorDiv);
    }

    clearFieldError(input) {
        input.classList.remove('error');
        const errorMessage = input.parentNode.querySelector('.error-message');
        if (errorMessage) {
            errorMessage.remove();
        }
    }

    async searchEquipment() {
        if (!this.validateParams()) {
            return;
        }

        try {
            console.log('Начинаем поиск оборудования...');
            console.log('Выбранные данные:', this.selectedData);
            
            // Загружаем данные из JSON файла напрямую
            const response = await fetch('/data.json');
            if (!response.ok) {
                throw new Error('Не удалось загрузить данные оборудования');
            }
            
            const equipmentData = await response.json();
            console.log('Данные оборудования загружены:', equipmentData);
            
            // Выполняем поиск локально
            const matchingEquipment = this.findMatchingEquipment(equipmentData);
            console.log('Найдено оборудования:', matchingEquipment.length);
            
            // Сохраняем результаты в localStorage
            localStorage.setItem('searchResults', JSON.stringify(matchingEquipment));
            localStorage.setItem('searchParams', JSON.stringify(this.selectedData));
            
            // Перенаправляем на страницу результатов
            const urlParams = new URLSearchParams();
            urlParams.set('medium', this.selectedData.medium);
            urlParams.set('application', this.selectedData.application);
            if (this.selectedData.gasType) {
                urlParams.set('gas_type', this.selectedData.gasType);
            }
            
            // Добавляем параметры поиска
            const params = this.selectedData.params;
            if (params.flowMin !== undefined) urlParams.set('flow_min', params.flowMin);
            if (params.flowMax !== undefined) urlParams.set('flow_max', params.flowMax);
            if (params.flowUnit !== undefined) urlParams.set('flow_unit', params.flowUnit);
            if (params.pressureMin !== undefined) urlParams.set('pressure_min', params.pressureMin);
            if (params.pressureMax !== undefined) urlParams.set('pressure_max', params.pressureMax);
            if (params.pressureUnit !== undefined) urlParams.set('pressure_unit', params.pressureUnit);
            if (params.tempMediumMin !== undefined) urlParams.set('temperature_min', params.tempMediumMin);
            if (params.tempMediumMax !== undefined) urlParams.set('temperature_max', params.tempMediumMax);
            if (params.tempUnit !== undefined) urlParams.set('temperature_unit', params.tempUnit);
            if (params.tempAmbientMin !== undefined) urlParams.set('ambient_temp_min', params.tempAmbientMin);
            if (params.tempAmbientMax !== undefined) urlParams.set('ambient_temp_max', params.tempAmbientMax);
            if (params.accuracy !== undefined) urlParams.set('accuracy', params.accuracy);
            if (params.diameter !== undefined) urlParams.set('diameter', params.diameter);
            if (params.densityMin !== undefined) urlParams.set('density_min', params.densityMin);
            if (params.densityMax !== undefined) urlParams.set('density_max', params.densityMax);
            
            window.location.href = `/results?${urlParams.toString()}`;

        } catch (error) {
            console.error('Ошибка поиска:', error);
            this.showError('Ошибка поиска', `Error: ${error.message}`);
        }
    }

    findMatchingEquipment(equipmentData) {
        const matching = [];
        const medium = this.selectedData.medium;
        const application = this.selectedData.application;
        const gasType = this.selectedData.gasType;
        
        console.log('Поиск оборудования для:', { medium, application, gasType });
        
        // Определяем путь к данным в JSON
        let dataPath;
        if (medium === 'gas') {
            if (application === 'utility') {
                dataPath = equipmentData.gas.utility;
            } else if (application === 'industrial') {
                if (gasType === 'natural') {
                    dataPath = equipmentData.gas.industrial.natural;
                } else if (gasType === 'technological') {
                    dataPath = equipmentData.gas.industrial.technological;
                }
            }
        } else if (medium === 'liquid' && application === 'industrial') {
            dataPath = equipmentData.liquid.industrial;
        }
        
        if (!dataPath) {
            console.log('Путь к данным не найден');
            return [];
        }
        
        console.log('Найден путь к данным, количество оборудования:', dataPath.length);
        
        // Фильтруем оборудование по параметрам
        for (const equipment of dataPath) {
            console.log('Проверяем оборудование:', equipment.name);
            const suitable = this.isEquipmentSuitable(equipment);
            console.log('Подходит:', suitable);
            
            if (suitable) {
                // Форматируем данные для отображения
                const formattedEquipment = {
                    id: equipment.id,
                    name: equipment.name,
                    manufacturer: equipment.manufacturer,
                    model: equipment.model,
                    image: equipment.image,
                    flow_range: equipment.specs.flowRange,
                    pressure_range: equipment.specs.pressureRange,
                    temperature_range: equipment.specs.tempRange,
                    accuracy: equipment.specs.accuracy,
                    diameter: equipment.specs.diameter,
                    medium: medium === 'gas' ? 'Газ' : 'Жидкость',
                    application: application === 'industrial' ? 'Промышленное' : 'Коммунальное'
                };
                matching.push(formattedEquipment);
            }
        }
        
        return matching;
    }
    
    isEquipmentSuitable(equipment) {
        const params = this.selectedData.params;
        console.log('Проверяем параметры:', params);
        console.log('Спецификации оборудования:', equipment.specs);
        
        // Проверяем расход
        if (params.flowMin !== undefined || params.flowMax !== undefined) {
            const flowRange = this.parseRange(equipment.specs.flowRange);
            console.log('Диапазон расхода оборудования:', flowRange);
            console.log('Требуемый диапазон расхода:', { min: params.flowMin, max: params.flowMax });
            
            if (flowRange) {
                if (params.flowMin !== undefined && flowRange.max < parseFloat(params.flowMin)) {
                    console.log('Не подходит: максимальный расход оборудования меньше минимального требуемого');
                    return false;
                }
                if (params.flowMax !== undefined && flowRange.min > parseFloat(params.flowMax)) {
                    console.log('Не подходит: минимальный расход оборудования больше максимального требуемого');
                    return false;
                }
            }
        }
        
        // Проверяем давление
        if (params.pressureMin !== undefined || params.pressureMax !== undefined) {
            const pressureRange = this.parseRange(equipment.specs.pressureRange);
            if (pressureRange) {
                if (params.pressureMin !== undefined && pressureRange.max < parseFloat(params.pressureMin)) return false;
                if (params.pressureMax !== undefined && pressureRange.min > parseFloat(params.pressureMax)) return false;
            }
        }
        
        // Проверяем температуру
        if (params.tempMediumMin !== undefined || params.tempMediumMax !== undefined) {
            const tempRange = this.parseRange(equipment.specs.tempRange);
            if (tempRange) {
                if (params.tempMediumMin !== undefined && tempRange.max < parseFloat(params.tempMediumMin)) return false;
                if (params.tempMediumMax !== undefined && tempRange.min > parseFloat(params.tempMediumMax)) return false;
            }
        }
        
        // Проверяем точность
        if (params.accuracy !== undefined) {
            const accuracyRange = this.parseRange(equipment.specs.accuracy);
            const requiredAccuracy = parseFloat(params.accuracy);
            console.log('Проверяем точность:', { equipmentRange: accuracyRange, required: requiredAccuracy });
            
            if (accuracyRange && !isNaN(requiredAccuracy)) {
                // Проверяем, что требуемая точность находится в диапазоне оборудования
                if (requiredAccuracy < accuracyRange.min || requiredAccuracy > accuracyRange.max) {
                    console.log('Не подходит: требуемая точность не входит в диапазон оборудования');
                    return false;
                }
            }
        }
        
        // Проверяем диаметр
        if (params.diameter !== undefined) {
            const diameterRange = this.parseRange(equipment.specs.diameter);
            const requiredDiameter = parseFloat(params.diameter);
            console.log('Проверяем диаметр:', { equipmentRange: diameterRange, required: requiredDiameter });
            
            if (diameterRange && !isNaN(requiredDiameter)) {
                // Проверяем, что требуемый диаметр находится в диапазоне оборудования
                if (requiredDiameter < diameterRange.min || requiredDiameter > diameterRange.max) {
                    console.log('Не подходит: требуемый диаметр не входит в диапазон оборудования');
                    return false;
                }
            }
        }
        
        // Проверяем температуру окружающей среды
        if (params.tempAmbientMin !== undefined || params.tempAmbientMax !== undefined) {
            const ambientTempRange = this.parseRange(equipment.specs.ambientTempRange);
            if (ambientTempRange) {
                if (params.tempAmbientMin !== undefined && ambientTempRange.max < parseFloat(params.tempAmbientMin)) {
                    console.log('Не подходит: максимальная температура окружающей среды оборудования меньше минимальной требуемой');
                    return false;
                }
                if (params.tempAmbientMax !== undefined && ambientTempRange.min > parseFloat(params.tempAmbientMax)) {
                    console.log('Не подходит: минимальная температура окружающей среды оборудования больше максимальной требуемой');
                    return false;
                }
            }
        }
        
        // Проверяем плотность (для жидкостей)
        if (params.densityMin !== undefined || params.densityMax !== undefined) {
            const densityRange = this.parseRange(equipment.specs.densityRange);
            if (densityRange) {
                if (params.densityMin !== undefined && densityRange.max < parseFloat(params.densityMin)) {
                    console.log('Не подходит: максимальная плотность оборудования меньше минимальной требуемой');
                    return false;
                }
                if (params.densityMax !== undefined && densityRange.min > parseFloat(params.densityMax)) {
                    console.log('Не подходит: минимальная плотность оборудования больше максимальной требуемой');
                    return false;
                }
            }
         }
         
         return true;
    }
    
    parseRange(rangeStr) {
        if (!rangeStr) return null;
        
        // Удаляем единицы измерения и лишние символы, оставляем цифры, запятые, точки и разделители диапазонов
        const cleanStr = rangeStr.replace(/[^0-9.,–-]/g, ' ').trim();
        
        // Ищем числа в строке
        const numbers = cleanStr.match(/[0-9]+[.,]?[0-9]*/g);
        if (!numbers || numbers.length === 0) return null;
        
        // Преобразуем запятые в точки и парсим числа
        const parsedNumbers = numbers.map(num => parseFloat(num.replace(',', '.')));
        
        // Если только одно число, используем его как точное значение
        if (parsedNumbers.length === 1) {
            return { min: parsedNumbers[0], max: parsedNumbers[0] };
        }
        
        // Если несколько чисел, берем минимальное и максимальное
        const min = Math.min(...parsedNumbers);
        const max = Math.max(...parsedNumbers);
        
        return { min, max };
    }

    displayResults(equipment, total) {
        const resultsContainer = document.getElementById('results-container');
        
        if (!equipment || equipment.length === 0) {
            resultsContainer.innerHTML = `
                <div class="results-header">
                    <div class="results-count">Результаты поиска: 0</div>
                </div>
                <div style="text-align: center; padding: 40px; color: #7f8c8d;">
                    <p>По заданным параметрам оборудование не найдено.</p>
                    <p>Попробуйте изменить критерии поиска.</p>
                </div>
            `;
            return;
        }

        let html = `
            <div class="results-header">
                <div class="results-count">Результаты поиска: ${total || equipment.length}</div>
            </div>
            <div class="results-list">
        `;

        equipment.forEach(item => {
            html += `
                <div class="result-item">
                    <div class="result-header">
                        <div>
                            <div class="result-name">${item.name || 'Не указано'}</div>
                            <div class="result-type">${item.type || 'Не указано'}</div>
                        </div>
                        <div class="result-match">Совпадение</div>
                    </div>
                    <div class="result-params">
            `;

            // Отобразить параметры оборудования
            const params = [
                { key: 'flow_range', name: 'Диапазон расхода' },
                { key: 'diameter', name: 'Диаметр' },
                { key: 'pressure_range', name: 'Диапазон давления' },
                { key: 'temperature_range', name: 'Диапазон температуры' },
                { key: 'accuracy', name: 'Точность' },
                { key: 'medium', name: 'Среда' },
                { key: 'application', name: 'Применение' }
            ];

            params.forEach(param => {
                if (item[param.key]) {
                    html += `
                        <div class="result-param">
                            <span class="param-name">${param.name}:</span>
                            <span class="param-value">${item[param.key]}</span>
                        </div>
                    `;
                }
            });

            html += `
                    </div>
                </div>
            `;
        });

        html += '</div>';
        resultsContainer.innerHTML = html;
    }

    showError(title, message) {
        const modal = document.getElementById('error-modal');
        const titleElement = document.getElementById('error-title');
        const messageElement = document.getElementById('error-message');

        if (titleElement) titleElement.textContent = title;
        if (messageElement) messageElement.textContent = message;
        if (modal) {
            modal.classList.add('show');
            modal.style.display = 'flex';
        }
    }

    hideModal() {
        const modal = document.getElementById('error-modal');
        if (modal) {
            modal.classList.remove('show');
            modal.style.display = 'none';
        }
    }

    reset() {
        // Сброс данных
        this.selectedData = {
            medium: null,
            application: null,
            gasType: null,
            params: {}
        };
        
        this.currentStep = 1;
        
        // Очистка форм
        document.querySelectorAll('input').forEach(input => {
            input.value = '';
            this.clearFieldError(input);
        });

        document.querySelectorAll('select').forEach(select => {
            select.selectedIndex = 0;
        });
        
        // Скрытие результатов
        const resultsSection = document.getElementById('results-section');
        if (resultsSection) {
            resultsSection.style.display = 'none';
        }
        
        // Показать первый шаг
        this.showStep(1);
        
        // Очистить ошибки
        const errorElements = document.querySelectorAll('.error-message');
        errorElements.forEach(el => el.remove());
        
        const errorFields = document.querySelectorAll('.error');
        errorFields.forEach(field => field.classList.remove('error'));
        
        // Очистить выбранные опции
        const selectedOptions = document.querySelectorAll('.option-card.selected');
        selectedOptions.forEach(option => option.classList.remove('selected'));
        
        // Очистить активные кнопки условий
        const activeConditions = document.querySelectorAll('.condition-btn.active');
        activeConditions.forEach(btn => btn.classList.remove('active'));
    }
}

// Инициализация приложения
document.addEventListener('DOMContentLoaded', () => {
    window.equipmentSelector = new EquipmentSelector();
});

// Навигация по клику на карточки (совместимо с текущей версткой)
// Страница "Сфера применения" (Шаг 3): выбор применения для газа
document.addEventListener('click', (e) => {
  const card = e.target.closest('.card[data-application]');
  if (!card) return;
  const params = new URLSearchParams(window.location.search);
  const equipmentType = params.get('equipment_type') || 'flowmeters';
  const medium = params.get('medium') || 'gas';
  const application = card.getAttribute('data-application');
  if (application === 'industrial') {
    window.location.href = `/gas-type?equipment_type=${encodeURIComponent(equipmentType)}&medium=${encodeURIComponent(medium)}&application=industrial`;
  } else if (application === 'utility') {
    // Для коммунально-бытового пропускаем выбор типа газа: natural
    window.location.href = `/params?equipment_type=${encodeURIComponent(equipmentType)}&medium=${encodeURIComponent(medium)}&application=utility&gas_type=natural`;
  }
});

// Страница "Тип газа" (Шаг 4): выбор типа газа
document.addEventListener('click', (e) => {
  const card = e.target.closest('.card[data-gas-type]');
  if (!card) return;
  const params = new URLSearchParams(window.location.search);
  const equipmentType = params.get('equipment_type') || 'flowmeters';
  const medium = params.get('medium') || 'gas';
  const application = params.get('application') || 'industrial';
  const gasType = card.getAttribute('data-gas-type');
  window.location.href = `/params?equipment_type=${encodeURIComponent(equipmentType)}&medium=${encodeURIComponent(medium)}&application=${encodeURIComponent(application)}&gas_type=${encodeURIComponent(gasType)}`;
});

// Кнопки Назад на страницах шагов
document.addEventListener('click', (e) => {
  const backBtn = e.target.closest('#back-btn-page');
  if (!backBtn) return;
  const params = new URLSearchParams(window.location.search);
  const equipmentType = params.get('equipment_type') || 'flowmeters';
  const medium = params.get('medium');
  const application = params.get('application');
  const gasType = params.get('gas_type');

  const path = window.location.pathname;
  if (path.includes('/measuring-instruments')) {
    // Со страницы КИП назад на главную
    window.location.href = '/';
  } else if (path.includes('/medium')) {
    // Со страницы выбора среды назад
    // Если это КИП (flowmeters, pressure, household) - к странице КИП
    if (['flowmeters', 'pressure', 'household'].includes(equipmentType)) {
      window.location.href = '/measuring-instruments';
    } else {
      // Для других категорий - на главную
      window.location.href = '/';
    }
  } else if (path.includes('/application')) {
    // Со страницы применения назад к выбору среды
    window.location.href = `/medium?equipment_type=${encodeURIComponent(equipmentType)}`;
  } else if (path.includes('/gas-type')) {
    // Со страницы типа газа назад к применению
    window.location.href = `/application?equipment_type=${encodeURIComponent(equipmentType)}&medium=${encodeURIComponent(medium || 'gas')}`;
  } else if (path.includes('/params')) {
    if (medium === 'gas' && application === 'industrial') {
      window.location.href = `/gas-type?equipment_type=${encodeURIComponent(equipmentType)}&medium=gas&application=industrial`;
    } else if (medium === 'gas') {
      window.location.href = `/application?equipment_type=${encodeURIComponent(equipmentType)}&medium=gas`;
    } else {
      window.location.href = `/medium?equipment_type=${encodeURIComponent(equipmentType)}`;
    }
  }
});