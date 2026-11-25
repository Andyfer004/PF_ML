FROM python:3.12-slim
WORKDIR /app
COPY requirements-api.lock ./
RUN pip install --no-cache-dir -r requirements-api.lock
COPY api ./api
COPY docs/informe.pdf docs/arquitectura_usuario.png ./docs/
COPY presentacion/presentacion_jurado.pdf presentacion/resumen_jurado.pdf ./presentacion/
USER 1000:1000
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
