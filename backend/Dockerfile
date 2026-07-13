FROM python:3.12-slim

WORKDIR /app
COPY app /app/app
COPY tests /app/tests
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -e .[dev]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
