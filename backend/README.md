# FORMA: backend de IA y servicios opcionales

FORMA mantiene las claves de proveedor fuera de la APK. Las claves viven como secretos del Worker de Cloudflare.

## Arquitectura de análisis

- **BodyComp** ejecuta la segmentación y la inferencia de composición corporal en el dispositivo. El código y sus pesos de inferencia se descargan desde una revisión fijada durante la compilación y se incluyen en la APK. En el análisis local, las fotografías no se envían al servidor.
- **MediaPipe** realiza detección/segmentación local. Si no inicia o no detecta la pose, FORMA sigue intentando el análisis de silueta; las comprobaciones de calidad determinan si se pueden mostrar cifras.
- **Gemini Visual** es un respaldo opcional. Solo recibe las fotos cuando el usuario activa explícitamente «Permitir análisis visual con Gemini». Analiza una o dos fotos, aunque estén recortadas o tengan una pose distinta, y describe lo que realmente puede observarse. No inventa perímetros ni masa muscular en kg.
- **Clad** es opcional y está desactivado por defecto. Solo recibe la primera foto y la estatura si el usuario activa el consentimiento específico. Clad puede requerir un plan o cuenta externa y no se utiliza para calcular grasa o músculo.
- **Gemini Coach** recibe la pregunta enviada. El resumen de perfil y progreso solo se incluye si el usuario activa «Personalizar respuestas con mis datos». No recibe fotografías desde el Coach.

Gemini usa la API de Interactions con `store: false`. Este parámetro desactiva el almacenamiento de la interacción por parte de la API, pero no sustituye la revisión de las condiciones de privacidad del proveedor. El contenido de planes gratuitos puede estar sujeto a condiciones diferentes de los planes de pago. Revisa las condiciones aplicables antes de activar el envío de fotos.

## Claves necesarias

No pegues claves en el chat ni en el código.

1. **Gemini**: crea una clave en [Google AI Studio](https://aistudio.google.com/api-keys).
2. **Cloudflare**: crea una cuenta y un API Token con permiso para desplegar Workers.
3. **GitHub**: en Settings → Secrets and variables → Actions, añade:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `GEMINI_API_KEY`
   - `CLAD_API_KEY` (opcional)

Clad no es necesario para compilar ni desplegar el flujo gratuito. Si no se configura `CLAD_API_KEY`, la opción de Clad mostrará que el servicio no está disponible, pero BodyComp y Gemini seguirán funcionando según sus permisos.

Las claves se usan únicamente en el workflow de despliegue para crear secretos de Cloudflare. No se guardan en el código ni en la APK.

## Servicios y límites

El Worker comprueba el origen de la aplicación Android, limita el tamaño del cuerpo de las solicitudes y aplica límites de solicitudes mediante bindings de Cloudflare:

- Coach: 20 solicitudes por minuto.
- Inicio de escáner / fallback / inicio de Clad: 5 solicitudes por minuto.
- Polling de Clad: 40 solicitudes por minuto para no cortar los trabajos asíncronos.

Los contadores de Cloudflare son aproximados y se aplican por ubicación; pueden permitir solicitudes por encima del umbral. Son una protección básica frente al abuso, no autenticación ni límites estrictos globales. Para una aplicación pública a escala, se debe añadir identidad de usuario y un limitador estricto si el coste lo requiere. CORS tampoco es autenticación.

## Rutas del Worker

- `POST /api/coach`: pregunta y contexto resumido opcional.
- `POST /api/scan-fallback`: una o dos imágenes para orientación visual.
- `POST /api/clad/scan`: inicia una reconstrucción con foto y estatura.
- `POST /api/clad/poll`: consulta el trabajo asíncrono sin exponer la clave Clad al teléfono.
- `GET /health`: indica qué secretos y bindings están configurados sin revelar sus valores.

El Worker valida que las URL de seguimiento de Clad permanezcan en `api.clad.you`. No permite que el teléfono utilice la clave del proveedor directamente.

## Pruebas y límites conocidos

- Las pruebas del Worker simulan llamadas a los proveedores y comprueban validación, CORS, rate limiting y tamaños de carga.
- La prueba de BodyComp compara la salida del pipeline con siluetas de referencia de su proyecto original.
- Estas pruebas no sustituyen pruebas de cámara en teléfonos físicos.
- Una foto única, parcial o con una silueta poco clara puede recibir una lectura visual, pero no necesariamente permite calcular porcentajes o perímetros fiables.
- La masa magra apendicular no equivale a toda la masa muscular corporal.
- Antes de publicar comercialmente, se deben conservar los avisos de licencia de BodyComp/MediaPipe y revisar las licencias de los datasets y modelos distribuidos.
