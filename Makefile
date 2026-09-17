.PHONY: install download convert build validate test run update clean

install: ## Установить зависимости в .venv
	python3 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -r requirements-dev.txt

download: ## Скачать исходные XLSX с cbr.ru в data/raw/
	.venv/bin/python src/download.py

convert: ## Конвертация XLSX -> CSV (data/processed/)
	.venv/bin/python src/convert.py

build: ## Собрать витрины для дэшборда (data/dashboard/)
	.venv/bin/python src/build_datasets.py

validate: ## Валидация данных + отчёт качества (data/quality/)
	.venv/bin/python src/validate.py

test: ## Тесты
	.venv/bin/pytest -q

run: ## Запустить дэшборд локально (http://localhost:8501)
	.venv/bin/streamlit run app/dashboard.py

update: ## Полное обновление: скачать -> конвертировать -> собрать -> провалидировать -> запушить
	bash scripts/update.sh

clean: ## Удалить сгенерированные данные (кроме raw)
	rm -rf data/processed/* data/dashboard/* data/quality/*
