# Control Tower - Backend API

Esta carpeta contiene la API y los servicios de monitoreo en segundo plano para el proyecto **Control Tower**. Está diseñado con **Python 3**, utilizando el microframework **Flask** para servir las peticiones HTTP y WebSockets, y **MongoDB** como base de datos para la persistencia del inventario y el historial de reportes.

## ⚙️ Características Principales

*   **REST API:** Para añadir, listar, editar y eliminar servidores.
*   **WebSockets (Flask-SocketIO):** Para emitir el estado en tiempo real a los clientes conectados (frontend).
*   **Daemon de Monitoreo (`monitor.py`):** Un proceso en segundo plano que realiza peticiones a las interfaces iLO de los servidores mediante solicitudes HTTPS con sesión y extrae la salud del hardware.
*   **Encriptación de Credenciales:** Manejo seguro de las contraseñas de las interfaces iLO a través del módulo `crypto.py` usando `cryptography`.

---

## 🛠️ Requisitos del Entorno

1. Python 3.9+ instalado en la máquina anfitriona.
2. Base de datos MongoDB ejecutándose localmente (`mongodb://localhost:27017`) o la URL correspondiente configurada en las variables de entorno.

## 🚀 Instalación y Configuración (Entorno Local)

Sigue estos pasos para arrancar el servidor backend en tu entorno de desarrollo.

### 1. Activar tu Entorno Virtual (Opcional, pero recomendado)
Si tienes un entorno virtual como `.venv`, actívalo primero.
```bash
# En Windows
python -m venv venv
venv\Scripts\activate
```

### 2. Instalar Dependencias
Asegúrate de tener instalados todos los paquetes requeridos especificados en `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 3. Variables de Entorno y Configuración
El sistema utiliza un archivo `.env` en la raíz de esta carpeta para la configuración principal (base de datos, puertos, etc.) y un archivo de llave para la encriptación (`ilo_master.key`). Asegúrate de que ambos existan y estén configurados correctamente.

Ejemplo de `.env`:
```env
MONGO_URI=mongodb://localhost:27017/
SECRET_KEY=tu_secreto_flask
```

### 4. Ejecutar la Aplicación
Para levantar el servidor web Flask (que inicializará Flask-SocketIO y los threads de monitoreo de fondo):

```bash
python app.py
```
> [!NOTE] 
> Por defecto, el backend corre de forma local en el puerto `http://localhost:5000`.

---

## 📁 Estructura Principal del Backend

- `app.py`: Punto de inicialización de Flask y registro de Blueprints.
- `monitor.py`: Scripts y demonios que se encargan del "deep-scan" (minado de datos de hardware en los servidores iLO).
- `routes/`: Directorio que contiene los endpoints agrupados por módulo (`metrics.py`, `reports.py`, etc.).
- `ilo.py` / `ilo_master.key`: Manejo de la conexión y encriptación de datos contra los iLOs remotos.
- `db.py`: Conexión e instancias de MongoDB (`pymongo`).
- `requirements.txt`: Lista de dependencias del proyecto.

## 📝 Logs

Si necesitas rastrear problemas en el escaneo de los iLO, la aplicación backend exporta bitácoras detalladas en el archivo local `monitor.log`. Encontrarás aquí respuestas fallidas de servidores, timeouts y excepciones procesadas por el motor de monitorización.
