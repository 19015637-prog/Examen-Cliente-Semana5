import asyncio
import aiohttp
import time
from abc import ABC, abstractmethod


URL_API = "http://ecomarket.local/api/v1"
TOKEN_SEGURIDAD = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9" 
ESPERA_INICIAL = 5
ESPERA_MAXIMA = 60

# REQUERIMIENTO 1: PATRÓN OBSERVER (15%) 
class ObservadorBase(ABC):
    @abstractmethod
    async def actualizar(self, datos_inventario):
        pass

# Módulo para imprimir en consola el stock bajo
class ModuloStock(ObservadorBase):
    async def actualizar(self, datos_inventario):
        print("\n[INFO] ModuloStock: Revisando existencias...")
        items = datos_inventario.get("productos", [])
        for item in items:
            if item.get("status") == "BAJO_MINIMO":
                nombre = item.get("nombre")
                cantidad = item.get("stock")
                print(f"  --> ALERTA: {nombre} tiene solo {cantidad} unidades.")

# Módulo para enviar alertas. Requerimiento 2: 25% de peticiones HTTP
class ModuloNotificaciones(ObservadorBase):
    async def actualizar(self, datos_inventario):
        print("[INFO] ModuloNotificaciones: Preparando envío de alertas...")
        items = datos_inventario.get("productos", [])
        
        async with aiohttp.ClientSession() as sesion_post:
            for item in items:
                if item.get("status") == "BAJO_MINIMO":
                    # Body JSON requerido por el examen
                    cuerpo_alerta = {
                        "producto_id": item.get("id"),
                        "stock_actual": item.get("stock"),
                        "stock_minimo": item.get("stock_minimo"),
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ") # Formato ISO
                    }
                    cabeceras = {"Authorization": f"Bearer {TOKEN_SEGURIDAD}"}
                    
                    try:
                        url_alertas = f"{URL_API}/alertas"
                        async with sesion_post.post(url_alertas, json=cuerpo_alerta, headers=cabeceras) as r:
                            if r.status == 201:
                                print(f"  --> Alerta enviada con éxito para ID: {item.get('id')}")
                    except Exception as err:
                        print(f"  --> No se pudo enviar alerta: {err}")

# REQUERIMIENTO 2 Y 3, MONITOR (50% Manejo API + 15% Polling) 
class MonitorEcoMarket:
    def __init__(self):
        self.observadores = []
        self.etag_actual = None
        self.ultimo_json = None
        self.tiempo_poll = ESPERA_INICIAL
        self.activo = True

    def registrar_modulo(self, modulo):
        self.observadores.append(modulo)

    async def obtener_inventario(self, session):
        # Headers con Token y ETag 
        headers = {
            "Authorization": f"Bearer {TOKEN_SEGURIDAD}",
            "Accept": "application/json"
        }
        if self.etag_actual:
            headers["If-None-Match"] = self.etag_actual

        try:
            # Timeout de 10 segundos 
            async with session.get(f"{URL_API}/inventario", headers=headers, timeout=10) as resp:
                
                # Caso 200: Datos nuevos
                if resp.status == 200:
                    self.etag_actual = resp.headers.get("ETag")
                    datos = await resp.json()
                    
                    # Invariante 6: Validar contenido
                    if datos and "productos" in datos:
                        self.tiempo_poll = ESPERA_INICIAL # Reset backoff
                        return datos
                    return None

                # Caso 304: Sin cambios
                elif resp.status == 304:
                    print("Status 304: El inventario sigue igual.")
                    # Aplicar Backoff (Invariante 3)
                    self.tiempo_poll = min(self.tiempo_poll * 2, ESPERA_MAXIMA)
                    return None

                # Caso 5xx: Error servidor
                elif resp.status >= 500:
                    print(f"Error {resp.status} en el servidor.")
                    self.tiempo_poll = min(self.tiempo_poll * 2, ESPERA_MAXIMA)
                    return None

        except Exception as e:
            # Invariante 1: No detener el ciclo por errores de red
            print(f"Error de red: {e}")
            self.tiempo_poll = min(self.tiempo_poll * 2, ESPERA_MAXIMA)
            return None

    async def ejecutar(self):
        print("--- SISTEMA INICIADO (Presiona Ctrl+C para salir) ---")
        async with aiohttp.ClientSession() as session:
            while self.activo:
                data = await self.obtener_inventario(session)
                
                # Notificar solo si hay cambios respecto al último estado
                if data and data != self.ultimo_json:
                    self.ultimo_json = data
                    for obs in self.observadores:
                        await obs.actualizar(data)
                
                print(f"Próxima revisión en {self.tiempo_poll} segundos...")
                # Invariante 3 No usar time.sleep(), usar asyncio.sleep()
                await asyncio.sleep(self.tiempo_poll)

    def cerrar(self):
        # Invariante 4: Cierre 
        self.activo = False

#  PUNTO DE ENTRADA 
async def principal():
    monitor = MonitorEcoMarket()
    
    # Suscribir los módulos requeridos
    monitor.registrar_modulo(ModuloStock())
    monitor.registrar_modulo(ModuloNotificaciones())
    
    try:
        await monitor.ejecutar()
    except KeyboardInterrupt:
        monitor.cerrar()
        print("\nMonitor detenido correctamente.")

if __name__ == "__main__":
    asyncio.run(principal())
