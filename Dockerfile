# Usar imagen base de Python oficial
FROM python:3.10-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de requerimientos e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código del backend
COPY . .

# Exponer el puerto definido en el .env (por defecto 5000)
EXPOSE 5000

# Comando para ejecutar la aplicación
# Usamos flask con socketio
CMD ["python", "app.py"]
