# SL Busslinje 528 – GPS-positioner i Home Assistant

Visar realtids-GPS för alla bussar på linje 528 direkt på HA:s karta.
Uppdateras var 15:e sekund via Trafiklabs GTFS Regional Realtime API.

## Installation via HACS

1. Öppna HACS i Home Assistant
2. Klicka på de tre prickarna uppe till höger → **Custom repositories**
3. Klistra in: `https://github.com/DITTNAMN/sl528-ha-integration`
4. Välj kategori: **Integration**
5. Klicka **Add** → sök på **SL Busslinje 528** → **Install**
6. Starta om Home Assistant

## Konfiguration

1. Gå till **Settings → Devices & Services → Add Integration**
2. Sök på **SL Busslinje 528**
3. Ange din API-nyckel från [trafiklab.se](https://trafiklab.se)
   - Skapa ett projekt och lägg till **GTFS Regional Realtime**
4. Klicka **Submit**

## Vad du får

- En `device_tracker`-entitet per buss i trafik just nu
- Visas automatiskt på HA:s inbyggda karta
- Attribut: hastighet (km/h), riktning, hållplatsnummer
- Uppdateras var 15:e sekund

## Felsökning

**Inga bussar syns** – Linje 528 kör inte just nu, eller fel API-nyckel.
Kontrollera under Settings → System → Logs och sök på `sl_528`.

**invalid_auth** – Kontrollera att du valt **GTFS Regional Realtime** i Trafiklab, inte GTFS Sverige eller ResRobot.
