## Cambio

Describe el problema y el comportamiento resultante para el usuario.

## Validación

- Windows: `windows/.venv/Scripts/python.exe -m pytest -q` desde `windows/`.
- Android: `./gradlew assembleDebug testDebugUnitTest` desde `android/`.
- Si cambia Android, actualizar el APK incluido en Windows.
- Comprobar que se conservan los vínculos, los datos y la firma del APK.

Al integrar en `main`, GitHub Actions publica una versión y las aplicaciones
con búsqueda automática activada avisan de la actualización.
