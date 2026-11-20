# FORMA: backend para Gemini y Clad

Las claves de proveedor viven como secretos del Worker de Cloudflare; no se incluyen en la APK.

## Qué procesa cada motor

- **BodyComp:** segmenta y analiza dos siluetas en el propio dispositivo. En FORMA 1.7 sus pesos estadísticos y el modelo de segmentación se empaquetan en la APK; una vez instalada, la inferencia no necesita descargar los pesos de BodyComp. El perfil adulto y los datos de referencia siguen siendo necesarios para el cálculo.
- **Gemini Visual:** analiza lo que aparezca en una o dos fotografías, aunque estén recortadas o tengan una pose distinta. Solo recibe las imágenes cuando el usuario activa la casilla de consentimiento específica. Su lectura es cualitativa; no inventa perímetros ni kilos de músculo.
- **Clad:** intenta reconstruir perímetros ISO a partir de una foto frontal y la estatura. Solo recibe esos datos cuando el usuario activa su casilla independiente. Clad no estima grasa ni masa muscular.
- **Gemini Coach:** recibe la pregunta y el contexto resumido necesario para personalizar la respuesta. No recibe fotografías desde el apartado Coach.

La aplicación puede mostrar resultados parciales: una estimación de composición puede conservarse aunque un motor no haya podido calcular todos los perímetros. Las estimaciones de fotografías no son mediciones clínicas.

## Privacidad

- BodyComp se ejecuta localmente y no transmite las fotografías.
- Gemini y Clad son servicios externos y requieren consentimiento separado en la pantalla del escáner.
- No se guardan fotografías en el historial local del escáner; solo se conservan fecha, proveedor y métricas resumidas.
- Gemini usa Interactions con `store: false`. Esto desactiva el almacenamiento de la interacción en esa API; no debe interpretarse como una promesa de que el proveedor no procese el contenido bajo sus condiciones aplicables.
- Antes de publicar, muestra un aviso de privacidad que identifique a los proveedores, su finalidad y las condiciones de tratamiento vigentes.

## Seguridad y límites del backend

El Worker valida el origen de Android WebView, limita cada cuerpo JSON a 12 MB incluso cuando no se envía Content-Length, valida los formatos de imagen, no registra el contenido de las imágenes y aplica timeouts a los servicios externos.

Se han configurado dos Rate Limiting bindings de Cloudflare:
- `COACH_RATE_LIMITER`: 30 solicitudes por 60 segundos y dirección IP, por ruta.
- `SCAN_RATE_LIMITER`: 12 solicitudes por 60 segundos y dirección IP, por ruta.

Los límites de Cloudflare son aproximados y se aplican por ubicación edge; pueden permitir ráfagas por encima del umbral. No sustituyen la autenticación ni son una protección estricta mundial. CORS tampoco es autenticación.

## Secretos necesarios

En GitHub → Settings → Secrets and variables → Actions:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `GEMINI_API_KEY`
- `CLAD_API_KEY`

No pegues estas claves en el código fuente ni en el chat. El workflow las publica como secretos del Worker.

## Rutas

- `POST /api/coach`: pregunta y contexto resumido.
- `POST /api/scan-fallback`: una o dos fotografías autorizadas para Gemini Visual.
- `POST /api/clad/scan`: inicia la reconstrucción con foto frontal y estatura.
- `POST /api/clad/poll`: consulta el trabajo sin revelar la clave de Clad.
- `GET /health`: informa si los proveedores y los limitadores están configurados, sin revelar claves.

## Pruebas y límites de validación

El backend tiene pruebas automáticas para CORS, Coach, Gemini con una foto, Clad, validación de las URL de sondeo, límites de solicitudes y cuerpos JSON demasiado grandes.

La prueba de BodyComp compara el modelo con siluetas de referencia publicadas. Es una prueba de paridad del modelo, no una validación clínica ni una prueba de todas las cámaras Android. Antes de distribución comercial deben realizarse pruebas físicas con fotos de consentimiento de personas adultas, revisar los intervalos de error y verificar las licencias de los modelos y datos. El conjunto BodyM tiene licencia CC BY-NC 4.0: no incluir sus fotografías en una aplicación comercial.