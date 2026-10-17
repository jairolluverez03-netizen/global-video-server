# Global Video Server

Aplicación independiente de Global Training. Genera MP4 con imagen fija y voz española Piper. La animación facial no está instalada.

## Acceso

La interfaz utiliza usuario y contraseña y una cookie de sesión segura, HttpOnly, SameSite Strict, de ocho horas. Configurar LOGIN_USERNAME y LOGIN_PASSWORD_HASH en Render, nunca en este repositorio. El hash tiene formato iteraciones$salt_hex$pbkdf2_sha256_hex, con 600000 iteraciones. VIDEO_API_TOKEN sigue siendo un secreto exclusivo del servidor para integraciones.

POST /api/login recibe username y password. GET /api/session consulta el acceso y POST /api/logout cierra la sesión del navegador. Cinco intentos fallidos por dirección en cinco minutos. Los cambios de contraseña en la configuración invalidan sesiones anteriores.

Docker instala la voz es_ES-davefx-medium y FFmpeg. Render usa el plan gratuito sin disco persistente: descargar los videos terminados porque pueden perderse al reiniciar o desplegar. Máximo 30 minutos de audio; la generación larga puede ser lenta en este plan. Un solo propietario y trabajador.

## API

GET /health público. /api/capabilities y /api/jobs requieren sesión o autorización de servidor. POST /api/jobs recibe title, script, engine, image y audio opcionales. GET /api/jobs/{id} consulta estado y GET /api/jobs/{id}/video descarga el MP4.

SadTalker es opcional, no incluido ni probado. No promete movimiento corporal.
