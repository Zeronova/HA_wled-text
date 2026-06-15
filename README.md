# WLED Text Display

Zeigt Text auf WLED-Segmenten an – entweder manuell gesetzt oder automatisch via Jinja2-Vorlage aus Sensorwerten.

## Wozu es da ist

Die offizielle WLED-Integration unterstützt kein Setzen von Text auf Segmenten (`seg[i].n`). Diese Integration schliesst die Lücke: Pro Segment wird ein `text`-Entity erstellt, das per `text.set_value` oder über eine Vorlage automatisch befüllt wird.

Sobald sich der Wert einer eingebundenen Entität ändert, wird der Text aktualisiert und per WLED JSON API auf das Display geschrieben.

## Installation

1. Repository als Custom Repository in HACS hinzufügen:
   - **URL:** `https://github.com/Zeronova/HA_wled-text`
   - **Kategorie:** Integration
2. Integration in HACS installieren
3. Home Assistant neustarten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → WLED Text Display**
5. IP-Adresse und optionalen Anzeigenamen eingeben

## Konfiguration

Nach dem Hinzufügen erscheint ein Gerät pro WLED-Controller mit einem `text`-Entity pro Segment.

### Manuelle Steuerung

Das Entity verhält sich wie ein normales `text`-Entity und kann per Automation oder Service aufgerufen werden:

```yaml
service: text.set_value
target:
  entity_id: text.wled_segment_0
data:
  value: "Hallo Welt"
```

### Automatisch via Vorlage

In den Optionen der Integration (Geräte & Dienste → WLED Text → Konfigurieren) kann pro Segment eine Jinja2-Vorlage hinterlegt werden. Der Vorlagen-Text wird dann automatisch auf das Display geschrieben und bei jeder Änderung der eingebundenen Entitäten aktualisiert.

**Beispiele:**

```
{{ state_translated('sensor.temperatur') }}
```

```
🌡️ {{ states('sensor.temperatur') }}°C
```

```
Heizung: {{ state_translated('climate.wohnzimmer') }}
```

Wird eine Vorlage gesetzt, überschreibt deren Ergebnis den manuell gesetzten Text.
