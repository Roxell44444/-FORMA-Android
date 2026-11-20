# FORMA: backend seguro para Gemini y Clad

La aplicación no contiene claves de proveedor. Las claves viven como secretos del Worker de Cloudflare.

## Qué servicios usa FORMA

- **BodyComp** analiza las fotos frontal y lateral en el teléfono. Las fotos no salen del dispositivo para este análisis.
- **Clad** (opcional, con consentimiento independiente) recibe solo la foto frontal y la estatura para reconstruir un modelo 3D y devolver perímetros ISO. Su función comercial de composición corporal sigue en desarrollo; FORMA no utiliza Clad para calcular grasa o músculo.
- **Gemini Coach** recibe la pregunta y un resumen del perfil/seguimiento solo si el usuario lo autoriza. No recibe fotos.
- **Gemini visual de respaldo** solo recibe la foto frontal y lateral si los motores principales no producen un resultado y el usuario marcó su consentimiento. Solo puede describir la calidad de las fotos y dar orientación cualitativa; nunca devolver cifras corporales.

Gemini usa la API de Interactions con `store: false`. El plan gratuito de Gemini puede utilizar el contenido enviado para mejorar productos de Google. En el plan de pago, Google indica que el contenido no se utiliza con ese fin. Lee las condiciones vigentes antes de activar el envío de fotos.

## Claves necesarias (no las pegues en el chat ni en el código)

1. **Gemini:** crea una clave en [Google AI Studio](https://aistudio.google.com/api-keys).
2. **Clad:** crea una clave de API en [Clad Developers](https://clad.you/developers).
3. **Cloudflare:** crea una cuenta gratuita y un API Token con permiso para desplegar Workers.
4. **GitHub:** en el repositorio, abre Settings → Secrets and variables → Actions → New repository secret y añade:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `GEMINI_API_KEY`
   - `CLAD_API_KEY`

Las claves se usan únicamente en el workflow de despliegue para crear secretos en Cloudflare. No se guardan en los archivos del proyecto ni en el APK.

## Desplegar el backend

1. Ejecuta el workflow **Deploy FORMA AI backend** desde GitHub → Actions.
2. El workflow publica `backend/worker.js` y registra las claves como secretos de Cloudflare.
3. Copia la URL que muestra el despliegue, por ejemplo `https://forma-ai-worker.<tu-subdominio>.workers.dev`.
4. Edita `assets/backend-config.json` y reemplaza `apiBaseUrl` por esa URL, sin una barra final.
5. Confirma ese cambio en GitHub. Se iniciará una nueva compilación Android con el backend configurado.

El backend comprueba el origen `https://appassets.androidplatform.net`, limita el tamaño de las imágenes y no escribe el contenido de los usuarios en logs. Configura además una regla de límite de solicitudes en Cloudflare para las rutas `/api/*` antes de publicar la app; CORS no es un sistema de autenticación ni evita el abuso del endpoint desde scripts.

## Rutas protegidas

- `POST /api/coach`: pregunta + contexto resumido.
- `POST /api/scan-fallback`: dos fotos, solo en el modo visual cualitativo.
- `POST /api/clad/scan`: inicia el trabajo asíncrono de reconstrucción con foto frontal + estatura.
- `POST /api/clad/poll`: consulta el trabajo sin exponer la clave de Clad al teléfono.
- `GET /health`: informa si cada secreto está configurado, sin revelar su contenido.

El Worker valida que las URL de consulta de Clad permanezcan en `api.clad.you`; no permite que el móvil use la clave directamente.

## Pruebas

La validación de modelos de BodyComp debe ejecutarse con las máscaras y valores de referencia del proyecto, en un paso de CI temporal. El dataset BodyM tiene licencia CC BY-NC 4.0: no se incluye en el APK ni debe reutilizarse como contenido de una versión comercial. Las pruebas con fotos reales capturadas por cámaras Android deben completarse en dispositivos físicos; la compilación de GitHub no puede certificar el comportamiento de todas las cámaras.
