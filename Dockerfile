FROM mcr.microsoft.com/playwright/python:v1.62.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 10000
CMD ["gunicorn","app:app","--bind","0.0.0.0:10000","--workers","1","--threads","4","--timeout","120"]
