# Usa la imagen oficial de Python
FROM python:3.11-slim

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia los archivos de dependencias
COPY requirements.txt .

# Instala las dependencias necesarias y gunicorn
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# Copia todo el código de la aplicación
COPY . .

# Expone el puerto 8080 (Cloud Run escucha en este puerto)
EXPOSE 8080

# Comando para ejecutar la aplicación con Gunicorn
# "app:app" -> archivo app.py y variable app de Flask
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]