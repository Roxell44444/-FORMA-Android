# FORMA: servicios inteligentes opcionales

El APK no contiene claves de proveedor. El Coach y el respaldo visual solo hacen peticiones cuando el usuario marca sus consentimientos. El respaldo visual no genera porcentajes ni medidas corporales.

## Configuración del servicio Gemini

1. Crea un proyecto de Cloudflare Workers y entra en esta carpeta: \`backend/\`.
2. Instala Wrangler y autentícate: \`npm install -g wrangler\` y \`wrangler login\`.
3. Guarda la clave como secreto del servidor: \`wrangler secret put GEMINI_API_KEY\`.
4. Despliega con \`wrangler deploy\`.
5. Copia la URL HTTPS del Worker en \`FORMA-1.1.0/public/config.json\`, en el campo \`apiBaseUrl\`, sin añadir una ruta al final.
6. Ejecuta de nuevo el workflow Android para empaquetar esa configuración.

La clave solo se guarda como secreto del Worker. No la escribas en \`config.json\`, en el código Android ni en GitHub.

## Consentimiento y tratamiento de datos

- Coach: solo se envía la pregunta y un resumen del perfil/resultado cuando el usuario lo autoriza.
- Respaldo visual: solo se envían las dos imágenes cuando el análisis principal falla y el usuario autorizó expresamente ese envío.
- El Worker no escribe las imágenes ni el contexto en logs.
- El nivel gratuito de Gemini puede utilizar las solicitudes para mejorar productos de Google. El texto de consentimiento de FORMA avisa de ello. Comprueba las condiciones vigentes antes de activar el servicio para usuarios.

El Worker debe limitarse a las rutas descritas y conviene aplicar reglas de seguridad/rate limiting en Cloudflare antes de abrirlo al público.

## Estado de Clad

Clad no está activado en este build. Su API para reconstrucción 3D y medidas está anunciada como disponible, pero su propia página presenta Fitness & Body Composition como función en desarrollo. El endpoint exacto de fotografía debe verificarse con el contrato oficial y una clave propia; FORMA no inventa rutas ni envía fotos a una API no verificada. Clad tampoco se usa para fingir un resultado de grasa o músculo.

## BodyComp

El código de inferencia se incorpora desde el proyecto MIT de BodyComp y se conserva su licencia. Los pesos de sus modelos se solicitan desde la distribución pública fijada a un commit concreto, no se empaquetan dentro del APK. El modelo de segmentación de MediaPipe se incorpora por separado. La estimación de BodyComp es orientativa, fue evaluada por los autores contra DXA, y no sustituye una medición clínica.
